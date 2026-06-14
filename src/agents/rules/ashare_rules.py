# -*- coding: utf-8 -*-
"""
A 股特有规则引擎：ST 风险、涨跌停、T+1 约束、停牌。

这些规则基于 ashare_flags（ChinaDataAssembler 从 get_stock_flags 获取），
用于分析师标记 A 股特有的风险/机会信号。

注意：ashare_flags 的规则主要产生 NEUTRAL 方向的"标记信号"，
真实方向影响由 trend/volume_price/money_flow 规则决定。
ashare 规则的作用是：标记风险，并在 ST/涨停等极端情况下调整强度。
"""
from __future__ import annotations

from typing import Any, Dict, List

from src.agents.rules.base import Signal


def evaluate(context: Dict[str, Any]) -> List[Signal]:
    """评估 A 股特有规则。依赖 context['ashare_flags']。"""
    signals: List[Signal] = []
    flags = context.get("ashare_flags") or {}
    if not isinstance(flags, dict) or not flags:
        return signals

    flag_list = flags.get("flags") or []
    if not isinstance(flag_list, list):
        flag_list = []
    flag_set = set(str(f).upper() for f in flag_list)

    name = str(flags.get("name", ""))
    change_pct = 0.0
    try:
        change_pct = float(flags.get("change_pct", 0.0))
    except (TypeError, ValueError):
        change_pct = 0.0

    # 规则 1：ST 风险标记
    if "ST" in flag_set or flags.get("is_st"):
        signals.append(Signal(
            rule="ST_STOCK_RISK",
            direction="BEAR",
            strength=70.0,
            description=f"{name} 为 ST/*ST 股票，存在退市风险，涨跌停限制为 ±5%",
            evidence={"name": name, "flags": list(flag_set)},
            category="ashare",
        ))

    # 规则 2：涨停标记（首板/连板需历史序列，这里标记当日涨停状态）
    if "LIMIT_UP" in flag_set or flags.get("limit_up"):
        # 涨停是强势信号，但买入风险高（次日可能低开）
        signals.append(Signal(
            rule="LIMIT_UP_TODAY",
            direction="BULL",
            strength=65.0,
            description=f"{name} 当日涨停(+{change_pct:.1f}%)，多头强势，但追涨风险高",
            evidence={"name": name, "change_pct": change_pct},
            category="ashare",
        ))

    # 规则 3：跌停标记
    if "LIMIT_DOWN" in flag_set or flags.get("limit_down"):
        signals.append(Signal(
            rule="LIMIT_DOWN_TODAY",
            direction="BEAR",
            strength=75.0,
            description=f"{name} 当日跌停({change_pct:.1f}%)，空头极强，流动性风险高",
            evidence={"name": name, "change_pct": change_pct},
            category="ashare",
        ))

    # 规则 4：停牌标记
    if "SUSPENDED" in flag_set or flags.get("suspended"):
        signals.append(Signal(
            rule="SUSPENDED",
            direction="NEUTRAL",
            strength=90.0,
            description=f"{name} 当前停牌，无法交易",
            evidence={"name": name, "flags": list(flag_set)},
            category="ashare",
        ))

    return signals
