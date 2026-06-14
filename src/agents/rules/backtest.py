# -*- coding: utf-8 -*-
"""
规则引擎回测验证模块。

目标：在历史 K 线上逐日跑 trend 规则，验证信号的统计有效性。
不模拟交易（那是 backtest_runner 的事），只统计：信号发出后未来 N 日
收益方向是否与信号方向一致（命中率/准确率）。

核心函数：
- backtest_trend_signals(df, forward_days) → 逐日信号 + 未来收益 + 命中统计
- summarize_backtest(records) → 按规则聚合命中率
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from src.agents.rules.base import Signal, signal_to_score
from src.agents.rules import trend_rules


@dataclass
class SignalRecord:
    """单条回测记录：某日某信号 + 未来收益。"""

    date: str
    rule: str
    direction: str  # BULL / BEAR / NEUTRAL
    strength: float
    close_at_signal: float
    forward_return_pct: float  # 未来 N 日收益率
    hit: bool  # 信号方向是否与未来收益方向一致
    forward_days: int


def backtest_trend_signals(
    df: pd.DataFrame,
    *,
    forward_days: int = 5,
    min_strength: float = 55.0,
) -> dict[str, Any]:
    """在历史 K 线上逐日跑 trend 规则，统计信号命中率。

    Args:
        df: 历史 K 线 DataFrame，需含 date/open/high/low/close 列（可选 volume）
        forward_days: 未来收益计算天数（默认 5 日）
        min_strength: 只统计强度 >= 此值的信号（过滤弱信号噪音）

    Returns:
        {
            "records": List[SignalRecord.to_dict()],
            "summary": {total_signals, hit_count, hit_rate, by_rule: {...}},
            "forward_days": int,
        }
    """
    if df is None or df.empty or len(df) < forward_days + 30:
        return {"records": [], "summary": _empty_summary(forward_days), "forward_days": forward_days}

    # 确保列名小写
    df_work = df.copy()
    df_work.columns = [str(c).lower() for c in df_work.columns]

    records: list[SignalRecord] = []
    closes = df_work["close"].tolist()
    dates = df_work["date"].tolist() if "date" in df_work.columns else list(range(len(df_work)))

    # 逐日跑 trend 规则（从第 30 行开始，确保均线有足够数据）
    for i in range(30, len(df_work) - forward_days):
        window = df_work.iloc[: i + 1]
        latest_row = window.iloc[-1]

        # 构造 indicators dict（与 trend_rules.evaluate 输入一致）
        indicators = {
            "MA5": _f(latest_row.get("sma_5")),
            "MA10": _f(latest_row.get("sma_10")),
            "MA20": _f(latest_row.get("sma_20")),
            "MA60": _f(latest_row.get("sma_60")),
            "MACD_DIF": _f(latest_row.get("macd_12_26_9")),
            "MACD_HIST": _f(latest_row.get("macdh_12_26_9")),
            "MACD_SIGNAL": _f(latest_row.get("macds_12_26_9")),
            "close": _f(latest_row.get("close")),
        }

        signals = trend_rules.evaluate(indicators)
        close_at_signal = closes[i]
        close_at_future = closes[i + forward_days]
        forward_return = (close_at_future - close_at_signal) / close_at_signal * 100 if close_at_signal else 0.0

        for sig in signals:
            if sig.strength < min_strength:
                continue
            # 命中判断：BULL 且未来涨、BEAR 且未来跌 → 命中
            if sig.direction == "BULL":
                hit = forward_return > 0
            elif sig.direction == "BEAR":
                hit = forward_return < 0
            else:
                hit = abs(forward_return) < 1.0  # 中性信号：未来波动 < 1% 算命中

            records.append(SignalRecord(
                date=str(dates[i]),
                rule=sig.rule,
                direction=sig.direction,
                strength=sig.strength,
                close_at_signal=round(close_at_signal, 4),
                forward_return_pct=round(forward_return, 2),
                hit=hit,
                forward_days=forward_days,
            ))

    return {
        "records": [_record_to_dict(r) for r in records],
        "summary": _summarize(records, forward_days),
        "forward_days": forward_days,
    }


def summarize_backtest(records: list[dict]) -> dict[str, Any]:
    """对已有的回测记录做聚合统计（供多次回测合并分析）。"""
    typed = [
        SignalRecord(
            date=str(r.get("date", "")),
            rule=str(r.get("rule", "")),
            direction=str(r.get("direction", "")),
            strength=float(r.get("strength", 0)),
            close_at_signal=float(r.get("close_at_signal", 0)),
            forward_return_pct=float(r.get("forward_return_pct", 0)),
            hit=bool(r.get("hit", False)),
            forward_days=int(r.get("forward_days", 5)),
        )
        for r in records
    ]
    return _summarize(typed, typed[0].forward_days if typed else 5)


def _summarize(records: list[SignalRecord], forward_days: int) -> dict[str, Any]:
    """聚合统计：总体命中率 + 按规则细分。"""
    if not records:
        return _empty_summary(forward_days)

    total = len(records)
    hits = sum(1 for r in records if r.hit)

    # 按规则细分
    by_rule: dict[str, dict[str, Any]] = {}
    for r in records:
        if r.rule not in by_rule:
            by_rule[r.rule] = {"total": 0, "hits": 0, "avg_return": 0.0, "direction": r.direction}
        by_rule[r.rule]["total"] += 1
        if r.hit:
            by_rule[r.rule]["hits"] += 1
        by_rule[r.rule]["avg_return"] += r.forward_return_pct

    for rule_data in by_rule.values():
        rule_data["hit_rate"] = round(rule_data["hits"] / rule_data["total"], 4) if rule_data["total"] else 0.0
        rule_data["avg_return"] = round(rule_data["avg_return"] / rule_data["total"], 2) if rule_data["total"] else 0.0

    return {
        "total_signals": total,
        "hit_count": hits,
        "hit_rate": round(hits / total, 4) if total else 0.0,
        "forward_days": forward_days,
        "by_rule": by_rule,
    }


def _empty_summary(forward_days: int) -> dict[str, Any]:
    return {"total_signals": 0, "hit_count": 0, "hit_rate": 0.0, "forward_days": forward_days, "by_rule": {}}


def _record_to_dict(r: SignalRecord) -> dict[str, Any]:
    return {
        "date": r.date,
        "rule": r.rule,
        "direction": r.direction,
        "strength": r.strength,
        "close_at_signal": r.close_at_signal,
        "forward_return_pct": r.forward_return_pct,
        "hit": r.hit,
        "forward_days": r.forward_days,
    }


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        result = float(value)
        return result if result == result else default
    except (TypeError, ValueError):
        return default
