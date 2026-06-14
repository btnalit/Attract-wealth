# -*- coding: utf-8 -*-
"""
A 股规则引擎库 (Rules Engine)

提供 4 类规则，每类返回结构化 Signal 列表：
- trend_rules: 趋势（均线排列、MACD、价格与 MA60）
- volume_price_rules: 量价（放量/缩量、量价背离、地量）
- ashare_rules: A 股特有（ST、涨停、跌停、停牌）
- money_flow_rules: 资金流（主力净流入、超大单、龙虎榜）

统一入口：evaluate_all(context) 跑全部规则并返回聚合结果。
"""
from src.agents.rules.base import (
    Signal,
    aggregate_signals,
    serialize_signals,
    signal_to_score,
)
from src.agents.rules import (
    ashare_rules,
    money_flow_rules,
    trend_rules,
    volume_price_rules,
)


def evaluate_all(context: dict) -> dict:
    """跑全部 4 类规则，返回 {signals, summary}。

    Args:
        context: ChinaDataAssembler 产出的完整 context

    Returns:
        {
            "signals": List[Signal.to_dict()],
            "summary": aggregate_signals() 的结果（score/confidence/bull_count/...）
        }
    """
    indicators = context.get("technical_indicators") or {}
    all_signals = []
    all_signals.extend(trend_rules.evaluate(indicators))
    all_signals.extend(volume_price_rules.evaluate(context))
    all_signals.extend(ashare_rules.evaluate(context))
    all_signals.extend(money_flow_rules.evaluate(context))

    summary = aggregate_signals(all_signals)
    return {
        "signals": [s.to_dict() for s in all_signals],
        "summary": summary,
    }


__all__ = [
    "Signal",
    "aggregate_signals",
    "serialize_signals",
    "signal_to_score",
    "evaluate_all",
    "trend_rules",
    "volume_price_rules",
    "ashare_rules",
    "money_flow_rules",
]
