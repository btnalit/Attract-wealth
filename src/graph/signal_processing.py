"""
Signal processing helpers for graph nodes.
"""
from __future__ import annotations

from typing import Any

from src.core.agent_state import AgentState


def _to_dict(payload: Any) -> dict[str, Any]:
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    if isinstance(payload, dict):
        return dict(payload)
    if hasattr(payload, "__dict__"):
        return dict(payload.__dict__)
    return {"raw": str(payload)}


def merge_analysis_report(state: AgentState, *, report_type: str, report: Any) -> dict[str, Any]:
    """Merge one analyst report into state-compatible mapping."""
    reports = state.get("analysis_reports", {})
    merged = dict(reports if isinstance(reports, dict) else {})
    merged[str(report_type)] = _to_dict(report)
    return merged


def normalize_debate_result(payload: Any) -> dict[str, Any]:
    """Normalize debate payload to plain dict."""
    data = _to_dict(payload)
    bull = data.get("bull_arguments", [])
    bear = data.get("bear_arguments", [])
    try:
        gap = float(data.get("sentiment_gap", 0.0))
    except (TypeError, ValueError):
        gap = 0.0
    return {
        "bull_arguments": [str(item) for item in bull] if isinstance(bull, list) else [str(bull)],
        "bear_arguments": [str(item) for item in bear] if isinstance(bear, list) else [str(bear)],
        "sentiment_gap": max(0.0, min(100.0, gap)),
        **{k: v for k, v in data.items() if k not in {"bull_arguments", "bear_arguments", "sentiment_gap"}},
    }


def build_signal_summary(state: AgentState) -> dict[str, Any]:
    """Build compact signal summary from analyst reports（加权平均 + 冲突检测 + 信号汇聚）。

    重构要点（A 股分析增强）：
    - 用加权平均替代简单平均：技术面40% / 基本面30% / 情绪20% / 资金面10%
    - 冲突检测：多空 stance 数量接近时降低最终置信度
    - 汇聚各 analyst 的 signals 字段为统一信号清单（供前端展示）
    """
    reports = state.get("analysis_reports", {})
    if not isinstance(reports, dict):
        reports = {}

    # 分析师权重：从 weights 模块获取（支持回测校准 + 环境变量覆盖）
    from src.agents.rules.weights import get_calibrated_weights
    _WEIGHTS = get_calibrated_weights()
    # 未识别的 analyst 默认权重 20

    bullish = 0
    bearish = 0
    neutral = 0
    all_signals: list[dict[str, Any]] = []
    weighted_score_sum = 0.0
    weight_total = 0.0
    simple_scores: list[float] = []  # 向后兼容 avg_score

    for key, item in reports.items():
        report = _to_dict(item)
        try:
            score = float(report.get("score", 0.0))
        except (TypeError, ValueError):
            score = 50.0
        simple_scores.append(score)

        # 按 analyst_type 加权（technical_agent → technical 等）
        a_type = str(report.get("analyst_type", key)).lower()
        weight = 20.0
        for prefix, w in _WEIGHTS.items():
            if prefix in a_type:
                weight = w
                break
        weighted_score_sum += score * weight
        weight_total += weight

        stance = str(report.get("stance", "")).strip().lower()
        if stance == "bullish":
            bullish += 1
        elif stance == "bearish":
            bearish += 1
        else:
            neutral += 1

        # 汇聚规则信号
        sigs = report.get("signals")
        if isinstance(sigs, list):
            for s in sigs:
                if isinstance(s, dict):
                    all_signals.append(s)

    # 加权综合分（向后兼容保留 avg_score = 简单平均）
    weighted_score = round(weighted_score_sum / weight_total, 3) if weight_total > 0 else 0.0
    avg_score = round(sum(simple_scores) / len(simple_scores), 3) if simple_scores else 0.0

    # 冲突检测：多空都 >= 2 且差距 <= 1
    total_stance = bullish + bearish + neutral
    conflict = bullish >= 2 and bearish >= 2 and abs(bullish - bearish) <= 1
    # 一致性置信度：|bull - bear| / total
    consistency = abs(bullish - bearish) / total_stance if total_stance > 0 else 0.0

    report_keys = sorted([str(key) for key in reports.keys()])
    return {
        "report_count": len(report_keys),
        "report_keys": report_keys,
        # 向后兼容字段
        "avg_score": avg_score,
        "bullish_count": bullish,
        "bearish_count": bearish,
        "has_complete_coverage": len(report_keys) >= 3,
        # 新增字段
        "weighted_score": weighted_score,
        "neutral_count": neutral,
        "conflict": conflict,
        "consistency": round(consistency, 3),
        "confidence": round(consistency * 100, 2),
        "all_signals": all_signals,
        "signal_count": len(all_signals),
    }


def build_signal_context_patch(state: AgentState) -> dict[str, Any]:
    """Build state patch with signal summary attached to context."""
    context = state.get("context", {})
    merged_context = dict(context if isinstance(context, dict) else {})
    merged_context["signal_summary"] = build_signal_summary(state)
    return {"context": merged_context}
