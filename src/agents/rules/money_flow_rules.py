# -*- coding: utf-8 -*-
"""
资金流规则引擎：主力净流入、超大单占比、龙虎榜机构席位。

输入：context dict（含 money_flow 和 dragon_tiger）
输出：List[Signal]

数据源：ChinaDataAssembler 从 get_money_flow / get_dragon_tiger 获取
"""
from __future__ import annotations

from typing import Any, Dict, List

from src.agents.rules.base import Signal


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        result = float(value)
        return result if result == result else default
    except (TypeError, ValueError):
        return default


def evaluate(context: Dict[str, Any]) -> List[Signal]:
    """评估资金流类规则。依赖 context['money_flow'] 和 context['dragon_tiger']。"""
    signals: List[Signal] = []
    money_flow = context.get("money_flow") or {}
    dragon_tiger = context.get("dragon_tiger") or []

    # ===== 资金流规则 =====
    if isinstance(money_flow, dict) and money_flow:
        main_net = _f(money_flow.get("main_net"))
        main_net_pct = _f(money_flow.get("main_net_pct"))
        super_large_net = _f(money_flow.get("super_large_net"))
        recent_main_sum = _f(money_flow.get("recent_main_net_sum"))
        history = money_flow.get("history") or []

        # 规则 1：主力当日净流入/流出
        if main_net != 0.0:
            if main_net > 0:
                strength = min(80.0, 55.0 + min(abs(main_net) / 1e8, 25))
                signals.append(Signal(
                    rule="MAIN_NET_INFLOW",
                    direction="BULL",
                    strength=strength,
                    description=f"主力资金净流入 {main_net/1e8:.2f} 亿{f'（占比 {main_net_pct:.1f}%）' if main_net_pct else ''}",
                    evidence={"main_net": main_net, "main_net_pct": main_net_pct},
                    category="money_flow",
                ))
            else:
                strength = min(80.0, 55.0 + min(abs(main_net) / 1e8, 25))
                signals.append(Signal(
                    rule="MAIN_NET_OUTFLOW",
                    direction="BEAR",
                    strength=strength,
                    description=f"主力资金净流出 {abs(main_net)/1e8:.2f} 亿{f'（占比 {main_net_pct:.1f}%）' if main_net_pct else ''}",
                    evidence={"main_net": main_net, "main_net_pct": main_net_pct},
                    category="money_flow",
                ))

        # 规则 2：近 N 日主力累计净流入（趋势性资金行为）
        if recent_main_sum != 0.0 and len(history) >= 3:
            if recent_main_sum > 0:
                strength = min(85.0, 60.0 + min(recent_main_sum / 1e8, 25))
                signals.append(Signal(
                    rule="MAIN_NET_INFLOW_TREND",
                    direction="BULL",
                    strength=strength,
                    description=f"近 {len(history)} 日主力累计净流入 {recent_main_sum/1e8:.2f} 亿，资金持续进场",
                    evidence={"recent_main_net_sum": recent_main_sum, "days": len(history)},
                    category="money_flow",
                ))
            else:
                strength = min(85.0, 60.0 + min(abs(recent_main_sum) / 1e8, 25))
                signals.append(Signal(
                    rule="MAIN_NET_OUTFLOW_TREND",
                    direction="BEAR",
                    strength=strength,
                    description=f"近 {len(history)} 日主力累计净流出 {abs(recent_main_sum)/1e8:.2f} 亿，资金持续撤离",
                    evidence={"recent_main_net_sum": recent_main_sum, "days": len(history)},
                    category="money_flow",
                ))

        # 规则 3：超大单动向
        if super_large_net != 0.0:
            if super_large_net > 0:
                signals.append(Signal(
                    rule="SUPER_LARGE_INFLOW",
                    direction="BULL",
                    strength=58.0,
                    description=f"超大单净流入 {super_large_net/1e8:.2f} 亿，机构/大资金买入",
                    evidence={"super_large_net": super_large_net},
                    category="money_flow",
                ))
            else:
                signals.append(Signal(
                    rule="SUPER_LARGE_OUTFLOW",
                    direction="BEAR",
                    strength=58.0,
                    description=f"超大单净流出 {abs(super_large_net)/1e8:.2f} 亿，机构/大资金卖出",
                    evidence={"super_large_net": super_large_net},
                    category="money_flow",
                ))

    # ===== 龙虎榜规则 =====
    if isinstance(dragon_tiger, list) and dragon_tiger:
        # 规则 4：龙虎榜上榜（关注度信号）
        signals.append(Signal(
            rule="DRAGON_TIGER_LISTED",
            direction="BULL",
            strength=60.0,
            description=f"近期登上龙虎榜 {len(dragon_tiger)} 次，市场关注度提升，游资/机构活跃",
            evidence={"appearances": len(dragon_tiger), "latest": dragon_tiger[0] if dragon_tiger else {}},
            category="money_flow",
        ))

        # 规则 5：龙虎榜净买入
        net_sum = sum(_f(item.get("net")) for item in dragon_tiger if isinstance(item, dict))
        if net_sum > 0:
            strength = min(78.0, 60.0 + min(net_sum / 1e8, 18))
            signals.append(Signal(
                rule="DRAGON_TIGER_NET_BUY",
                direction="BULL",
                strength=strength,
                description=f"龙虎榜席位累计净买入 {net_sum/1e8:.2f} 亿，资金看多",
                evidence={"net_sum": net_sum, "appearances": len(dragon_tiger)},
                category="money_flow",
            ))
        elif net_sum < 0:
            strength = min(78.0, 60.0 + min(abs(net_sum) / 1e8, 18))
            signals.append(Signal(
                rule="DRAGON_TIGER_NET_SELL",
                direction="BEAR",
                strength=strength,
                description=f"龙虎榜席位累计净卖出 {abs(net_sum)/1e8:.2f} 亿，资金看空",
                evidence={"net_sum": net_sum, "appearances": len(dragon_tiger)},
                category="money_flow",
            ))

    return signals
