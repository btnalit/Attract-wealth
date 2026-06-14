# -*- coding: utf-8 -*-
"""
A 股规则引擎核心数据模型 (Signal) + 信号聚合器。

设计原则：
- 每个规则返回结构化 Signal（不是一句话），可回测、可解释、可加权
- 方向统一用 BULL/BEAR/NEUTRAL，强度 0-100
- evidence 字段携带触发依据的原始数据快照，供前端展示和审计
- 聚合器支持加权平均 + 冲突检测（多空分歧大时降低置信度）
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List


@dataclass
class Signal:
    """单条规则信号。"""

    rule: str  # 规则名，如 "MA_GOLDEN_CROSS"
    direction: str  # BULL / BEAR / NEUTRAL
    strength: float = 50.0  # 0-100，越大越强
    description: str = ""  # 人类可读说明
    evidence: Dict[str, Any] = field(default_factory=dict)  # 触发依据的数据快照
    category: str = "misc"  # trend / volume_price / ashare / money_flow

    def __post_init__(self) -> None:
        # 方向归一化
        self.direction = self.direction.upper()
        if self.direction not in {"BULL", "BEAR", "NEUTRAL"}:
            self.direction = "NEUTRAL"
        # 强度边界
        self.strength = max(0.0, min(100.0, float(self.strength)))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# 方向 → 评分权重（BULL 加分，BEAR 减分，NEUTRAL 中性）
_DIRECTION_SCORE = {"BULL": 1.0, "NEUTRAL": 0.0, "BEAR": -1.0}


def signal_to_score(signal: Signal) -> float:
    """单条信号转 0-100 分：方向 × 强度。

    BULL → 50 + strength/2（范围 50-100）
    NEUTRAL → 50
    BEAR → 50 - strength/2（范围 0-50）
    """
    bias = _DIRECTION_SCORE.get(signal.direction, 0.0)
    return 50.0 + bias * (signal.strength / 2.0)


def aggregate_signals(
    signals: List[Signal],
    *,
    weights: Dict[str, float] | None = None,
) -> Dict[str, Any]:
    """聚合多个信号为综合评分 + 置信度 + 多空分布。

    Args:
        signals: 信号列表
        weights: 按 rule 名加权的字典（可选），未列出的规则权重为 1.0

    Returns:
        {
            "score": float,           # 0-100 综合评分
            "confidence": float,      # 0-100 置信度（信号一致性和数量决定）
            "bull_count": int,
            "bear_count": int,
            "neutral_count": int,
            "conflict": bool,         # 多空是否冲突（数量接近）
        }
    """
    if not signals:
        return {
            "score": 50.0,
            "confidence": 0.0,
            "bull_count": 0,
            "bear_count": 0,
            "neutral_count": 0,
            "conflict": False,
        }

    weights = weights or {}
    total_weight = 0.0
    weighted_score_sum = 0.0
    bull = bear = neutral = 0

    for sig in signals:
        w = float(weights.get(sig.rule, 1.0))
        total_weight += w
        weighted_score_sum += signal_to_score(sig) * w
        if sig.direction == "BULL":
            bull += 1
        elif sig.direction == "BEAR":
            bear += 1
        else:
            neutral += 1

    score = weighted_score_sum / total_weight if total_weight > 0 else 50.0
    score = max(0.0, min(100.0, round(score, 2)))

    # 置信度：信号数量 × 方向一致性
    # 一致性 = |bull - bear| / total，越一致置信度越高
    total = len(signals)
    consistency = abs(bull - bear) / total if total > 0 else 0.0
    # 数量因子：3 个信号 60%，6 个信号 100%（对数饱和）
    import math
    count_factor = min(1.0, math.log(max(total, 1) + 1) / math.log(7))
    confidence = round(consistency * 100 * count_factor, 2)

    # 冲突检测：多空数量都 >= 2 且差距 <= 1
    conflict = bull >= 2 and bear >= 2 and abs(bull - bear) <= 1

    return {
        "score": score,
        "confidence": confidence,
        "bull_count": bull,
        "bear_count": bear,
        "neutral_count": neutral,
        "conflict": conflict,
    }


def serialize_signals(signals: List[Signal]) -> str:
    """序列化信号列表为 LLM 友好的文本（供 analyst 把规则结论交给 LLM 解读）。"""
    if not signals:
        return "无可用规则信号。"
    lines = ["规则引擎产出的结构化信号（这些是确定性结论，请基于此综合判断）："]
    for sig in signals:
        lines.append(
            f"- [{sig.category}] {sig.rule}: {sig.direction} (强度 {sig.strength:.0f}/100) "
            f"— {sig.description}"
        )
    return "\n".join(lines)
