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
    """Build compact signal summary from analyst reports."""
    reports = state.get("analysis_reports", {})
    if not isinstance(reports, dict):
        reports = {}

    scores: list[float] = []
    bullish = 0
    bearish = 0
    for item in reports.values():
        report = _to_dict(item)
        try:
            score = float(report.get("score", 0.0))
            scores.append(score)
        except (TypeError, ValueError):
            pass
        stance = str(report.get("stance", "")).strip().lower()
        if stance == "bullish":
            bullish += 1
        elif stance == "bearish":
            bearish += 1

    avg_score = round(sum(scores) / len(scores), 3) if scores else 0.0
    report_keys = sorted([str(key) for key in reports.keys()])
    return {
        "report_count": len(report_keys),
        "report_keys": report_keys,
        "avg_score": avg_score,
        "bullish_count": bullish,
        "bearish_count": bearish,
        "has_complete_coverage": len(report_keys) >= 3,
    }


def build_signal_context_patch(state: AgentState) -> dict[str, Any]:
    """Build state patch with signal summary attached to context."""
    context = state.get("context", {})
    merged_context = dict(context if isinstance(context, dict) else {})
    merged_context["signal_summary"] = build_signal_summary(state)
    return {"context": merged_context}
