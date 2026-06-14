# -*- coding: utf-8 -*-
"""
板块联动规则引擎：个股与所属板块的共振分析。

输入：context dict（含 realtime/ashare_flags 的 change_pct + sector_info.sector_performance）
输出：List[Signal]

核心逻辑：
- 同向共振（个股+板块同涨/同跌）→ 强信号
- 逆势（个股与板块相反）→ 弱信号/中性
- 板块领涨股大涨 → 板块情绪好
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
    """评估板块联动规则。依赖 sector_info.sector_performance 和个股涨跌幅。"""
    signals: List[Signal] = []

    sector_info = context.get("sector_info") or {}
    if not isinstance(sector_info, dict) or not sector_info:
        return signals

    sector_perf = sector_info.get("sector_performance") or {}
    if not isinstance(sector_perf, dict) or not sector_perf:
        return signals

    sector_name = str(sector_perf.get("sector_name") or sector_info.get("industry") or "")
    sector_change = _f(sector_perf.get("sector_change_pct"))

    # 取个股涨跌幅（优先 realtime，其次 ashare_flags）
    realtime = context.get("realtime") or {}
    stock_change = _f(realtime.get("change_pct")) if isinstance(realtime, dict) else 0.0
    if stock_change == 0.0:
        flags = context.get("ashare_flags") or {}
        if isinstance(flags, dict):
            stock_change = _f(flags.get("change_pct"))

    if sector_change == 0.0 and stock_change == 0.0:
        return signals

    # 规则 1：同向共振（板块+个股同涨）
    if sector_change > 1.0 and stock_change > 1.0:
        strength = min(80.0, 55.0 + (sector_change + stock_change) / 2)
        signals.append(Signal(
            rule="SECTOR_BULLISH_RESONANCE",
            direction="BULL",
            strength=strength,
            description=f"板块共振：{sector_name} 板块涨 {sector_change:.1f}%，个股涨 {stock_change:.1f}%，同向走强",
            evidence={"sector_change_pct": sector_change, "stock_change_pct": stock_change, "sector": sector_name},
            category="sector",
        ))

    # 规则 2：同向共振（板块+个股同跌）
    elif sector_change < -1.0 and stock_change < -1.0:
        strength = min(80.0, 55.0 + abs(sector_change + stock_change) / 2)
        signals.append(Signal(
            rule="SECTOR_BEARISH_RESONANCE",
            direction="BEAR",
            strength=strength,
            description=f"板块共振：{sector_name} 板块跌 {sector_change:.1f}%，个股跌 {stock_change:.1f}%，同向走弱",
            evidence={"sector_change_pct": sector_change, "stock_change_pct": stock_change, "sector": sector_name},
            category="sector",
        ))

    # 规则 3：逆势上涨（板块跌但个股涨）
    elif sector_change < -1.0 and stock_change > 2.0:
        signals.append(Signal(
            rule="SECTOR_DIVERGENCE_UP",
            direction="BULL",
            strength=60.0,
            description=f"逆势走强：{sector_name} 板块跌 {abs(sector_change):.1f}% 但个股涨 {stock_change:.1f}%，独立行情",
            evidence={"sector_change_pct": sector_change, "stock_change_pct": stock_change, "sector": sector_name},
            category="sector",
        ))

    # 规则 4：逆势下跌（板块涨但个股跌）
    elif sector_change > 1.0 and stock_change < -2.0:
        signals.append(Signal(
            rule="SECTOR_DIVERGENCE_DOWN",
            direction="BEAR",
            strength=62.0,
            description=f"逆势走弱：{sector_name} 板块涨 {sector_change:.1f}% 但个股跌 {abs(stock_change):.1f}%，个股偏弱",
            evidence={"sector_change_pct": sector_change, "stock_change_pct": stock_change, "sector": sector_name},
            category="sector",
        ))

    # 规则 5：板块领涨股大涨（板块情绪好）
    leader_change = _f(sector_perf.get("leader_change_pct"))
    if leader_change > 5.0:
        leader = str(sector_perf.get("leader_stock") or "")
        signals.append(Signal(
            rule="SECTOR_LEADER_STRONG",
            direction="BULL",
            strength=55.0,
            description=f"板块领涨股 {leader} 大涨 {leader_change:.1f}%，{sector_name} 板块情绪活跃",
            evidence={"leader_stock": leader, "leader_change_pct": leader_change, "sector": sector_name},
            category="sector",
        ))

    # 规则 6：板块整体强势（板块涨幅 > 3%）
    if sector_change > 3.0:
        signals.append(Signal(
            rule="SECTOR_STRONG_TREND",
            direction="BULL",
            strength=min(70.0, 50.0 + sector_change * 3),
            description=f"{sector_name} 板块整体强势，涨幅 {sector_change:.1f}%，板块效应利好",
            evidence={"sector_change_pct": sector_change, "sector": sector_name},
            category="sector",
        ))
    elif sector_change < -3.0:
        signals.append(Signal(
            rule="SECTOR_WEAK_TREND",
            direction="BEAR",
            strength=min(70.0, 50.0 + abs(sector_change) * 3),
            description=f"{sector_name} 板块整体弱势，跌幅 {abs(sector_change):.1f}%，系统性风险",
            evidence={"sector_change_pct": sector_change, "sector": sector_name},
            category="sector",
        ))

    return signals
