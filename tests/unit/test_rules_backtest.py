# -*- coding: utf-8 -*-
"""规则引擎回测验证模块单元测试。"""
from __future__ import annotations

import pandas as pd

from src.agents.rules.backtest import backtest_trend_signals, summarize_backtest


def _make_synthetic_kline(n: int = 120, trend: str = "up") -> pd.DataFrame:
    """构造合成 K 线（带上行/下行趋势），含技术指标列名。

    trend='up' 生成持续上涨（触发均线多头排列），
    trend='down' 生成持续下跌（触发空头排列）。
    """
    rows = []
    base = 100.0
    for i in range(n):
        if trend == "up":
            close = base + i * 0.5 + (i % 3) * 0.2  # 整体上行 + 小波动
        else:
            close = base + (n - i) * 0.5 - (i % 3) * 0.2  # 整体下行
        rows.append({
            "date": f"2026-01-{(i % 28) + 1:02d}",
            "open": close - 0.3,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 1000000 + i * 10000,
            "sma_5": close - 0.2,
            "sma_10": close - 0.4,
            "sma_20": close - 0.8,
            "sma_60": close - 1.5,
            "macd_12_26_9": 0.5 if trend == "up" else -0.5,
            "macdh_12_26_9": 0.2 if trend == "up" else -0.2,
            "macds_12_26_9": 0.3 if trend == "up" else -0.3,
        })
    return pd.DataFrame(rows)


class TestBacktestTrendSignals:
    def test_uptrend_produces_bull_signals(self):
        df = _make_synthetic_kline(120, "up")
        result = backtest_trend_signals(df, forward_days=5, min_strength=55.0)
        assert len(result["records"]) > 0
        # 上涨趋势应主要产生 BULL 信号
        bull_count = sum(1 for r in result["records"] if r["direction"] == "BULL")
        assert bull_count > 0
        assert result["summary"]["total_signals"] == len(result["records"])

    def test_downtrend_produces_bear_signals(self):
        df = _make_synthetic_kline(120, "down")
        result = backtest_trend_signals(df, forward_days=5, min_strength=55.0)
        assert len(result["records"]) > 0
        bear_count = sum(1 for r in result["records"] if r["direction"] == "BEAR")
        assert bear_count > 0

    def test_uptrend_high_hit_rate(self):
        """持续上涨趋势中，BULL 信号命中率应较高（> 60%）。"""
        df = _make_synthetic_kline(120, "up")
        result = backtest_trend_signals(df, forward_days=5, min_strength=55.0)
        bull_records = [r for r in result["records"] if r["direction"] == "BULL"]
        if bull_records:
            bull_hits = sum(1 for r in bull_records if r["hit"])
            hit_rate = bull_hits / len(bull_records)
            assert hit_rate > 0.6, f"BULL 嫌中率过低: {hit_rate}"

    def test_summary_has_by_rule(self):
        df = _make_synthetic_kline(100, "up")
        result = backtest_trend_signals(df, forward_days=3, min_strength=50.0)
        assert "by_rule" in result["summary"]
        assert len(result["summary"]["by_rule"]) > 0
        # 每个规则应有 total/hits/hit_rate
        for rule, stats in result["summary"]["by_rule"].items():
            assert "total" in stats
            assert "hits" in stats
            assert "hit_rate" in stats

    def test_empty_df_returns_empty(self):
        result = backtest_trend_signals(pd.DataFrame(), forward_days=5)
        assert result["records"] == []
        assert result["summary"]["total_signals"] == 0

    def test_insufficient_data_returns_empty(self):
        df = _make_synthetic_kline(20, "up")  # 不够 30 + forward_days
        result = backtest_trend_signals(df, forward_days=5)
        assert result["records"] == []

    def test_summarize_backtest(self):
        records = [
            {"date": "d1", "rule": "MA_BULL", "direction": "BULL", "strength": 70,
             "close_at_signal": 100, "forward_return_pct": 2.0, "hit": True, "forward_days": 5},
            {"date": "d2", "rule": "MA_BULL", "direction": "BULL", "strength": 65,
             "close_at_signal": 101, "forward_return_pct": -1.0, "hit": False, "forward_days": 5},
        ]
        summary = summarize_backtest(records)
        assert summary["total_signals"] == 2
        assert summary["hit_count"] == 1
        assert summary["hit_rate"] == 0.5
        assert "MA_BULL" in summary["by_rule"]
