# -*- coding: utf-8 -*-
"""
A 股规则引擎单元测试。

覆盖：
- trend_rules: 均线排列、MACD、价格与 MA60
- volume_price_rules: 放量/缩量、量价背离
- ashare_rules: ST、涨停、跌停、停牌
- money_flow_rules: 主力净流入、龙虎榜
- base: Signal 数据模型、aggregate_signals 聚合、冲突检测
"""
from __future__ import annotations

from src.agents.rules import (
    ashare_rules,
    money_flow_rules,
    trend_rules,
    volume_price_rules,
)
from src.agents.rules.base import (
    Signal,
    aggregate_signals,
    serialize_signals,
    signal_to_score,
)


# ============================================
# base.py: Signal 数据模型
# ============================================
class TestSignalModel:
    def test_signal_normalizes_direction(self):
        s = Signal(rule="X", direction="bull", strength=70)
        assert s.direction == "BULL"

    def test_signal_clamps_strength(self):
        assert Signal(rule="X", direction="BULL", strength=150).strength == 100.0
        assert Signal(rule="X", direction="BULL", strength=-10).strength == 0.0

    def test_signal_invalid_direction_defaults_neutral(self):
        assert Signal(rule="X", direction="UNKNOWN").direction == "NEUTRAL"

    def test_signal_to_score_bull(self):
        s = Signal(rule="X", direction="BULL", strength=80)
        # 50 + 1.0 * 40 = 90
        assert signal_to_score(s) == 90.0

    def test_signal_to_score_bear(self):
        s = Signal(rule="X", direction="BEAR", strength=60)
        # 50 - 1.0 * 30 = 20
        assert signal_to_score(s) == 20.0

    def test_signal_to_score_neutral(self):
        s = Signal(rule="X", direction="NEUTRAL", strength=90)
        assert signal_to_score(s) == 50.0


# ============================================
# base.py: aggregate_signals
# ============================================
class TestAggregateSignals:
    def test_empty_signals_returns_neutral(self):
        result = aggregate_signals([])
        assert result["score"] == 50.0
        assert result["confidence"] == 0.0
        assert result["conflict"] is False

    def test_consistent_bull_signals_high_confidence(self):
        signals = [
            Signal(rule="A", direction="BULL", strength=70),
            Signal(rule="B", direction="BULL", strength=60),
            Signal(rule="C", direction="BULL", strength=80),
        ]
        result = aggregate_signals(signals)
        assert result["bull_count"] == 3
        assert result["bear_count"] == 0
        assert result["confidence"] > 50.0
        assert result["conflict"] is False

    def test_conflict_detection(self):
        signals = [
            Signal(rule="A", direction="BULL", strength=70),
            Signal(rule="B", direction="BULL", strength=60),
            Signal(rule="C", direction="BEAR", strength=80),
            Signal(rule="D", direction="BEAR", strength=70),
        ]
        result = aggregate_signals(signals)
        assert result["conflict"] is True
        assert result["confidence"] < 50.0  # 冲突时置信度低

    def test_serialize_signals_returns_text(self):
        signals = [Signal(rule="TEST", direction="BULL", strength=70, description="测试")]
        text = serialize_signals(signals)
        assert "TEST" in text
        assert "BULL" in text


# ============================================
# trend_rules: 均线排列
# ============================================
class TestTrendRules:
    def test_bullish_alignment_detected(self):
        indicators = {"MA5": 110, "MA10": 105, "MA20": 100, "MA60": 90, "close": 115}
        signals = trend_rules.evaluate(indicators)
        rules = [s.rule for s in signals]
        assert "MA_BULLISH_ALIGNMENT" in rules

    def test_bearish_alignment_detected(self):
        indicators = {"MA5": 90, "MA10": 95, "MA20": 100, "MA60": 105, "close": 85}
        signals = trend_rules.evaluate(indicators)
        rules = [s.rule for s in signals]
        assert "MA_BEARISH_ALIGNMENT" in rules

    def test_perfect_bullish_alignment_higher_strength(self):
        indicators = {"MA5": 110, "MA10": 105, "MA20": 100, "MA60": 90, "close": 115}
        signals = trend_rules.evaluate(indicators)
        alignment = next(s for s in signals if s.rule == "MA_BULLISH_ALIGNMENT")
        assert alignment.strength == 80.0  # 完美多头排列

    def test_macd_hist_positive(self):
        indicators = {"MA5": 10, "MA10": 10, "MA20": 10, "MACD_HIST": 0.5, "close": 10}
        signals = trend_rules.evaluate(indicators)
        assert any(s.rule == "MACD_HIST_POSITIVE" and s.direction == "BULL" for s in signals)

    def test_price_above_ma60(self):
        indicators = {"MA5": 100, "MA10": 100, "MA20": 100, "MA60": 90, "close": 105}
        signals = trend_rules.evaluate(indicators)
        assert any(s.rule == "PRICE_ABOVE_MA60" and s.direction == "BULL" for s in signals)

    def test_empty_indicators_returns_empty(self):
        assert trend_rules.evaluate({}) == []


# ============================================
# volume_price_rules: 量价规则
# ============================================
class TestVolumePriceRules:
    def _make_context(self, volumes, closes):
        kline = [{"date": f"2026-01-{i+1:02d}", "volume": v, "close": c} for i, (v, c) in enumerate(zip(volumes, closes))]
        return {"kline_recent": kline}

    def test_volume_breakout_up(self):
        # 放量上涨：最后一天成交量是均量 2 倍，价格上涨 5%
        volumes = [100, 100, 100, 100, 300]
        closes = [10.0, 10.0, 10.0, 10.0, 10.5]
        ctx = self._make_context(volumes, closes)
        signals = volume_price_rules.evaluate(ctx)
        assert any(s.rule == "VOLUME_BREAKOUT_UP" and s.direction == "BULL" for s in signals)

    def test_volume_breakout_down(self):
        volumes = [100, 100, 100, 100, 300]
        closes = [10.0, 10.0, 10.0, 10.0, 9.5]
        ctx = self._make_context(volumes, closes)
        signals = volume_price_rules.evaluate(ctx)
        assert any(s.rule == "VOLUME_BREAKOUT_DOWN" and s.direction == "BEAR" for s in signals)

    def test_volume_price_divergence(self):
        # 价涨量缩：价格涨 3%，成交量萎缩至 0.5 倍
        volumes = [200, 200, 200, 200, 100]
        closes = [10.0, 10.0, 10.0, 10.0, 10.35]
        ctx = self._make_context(volumes, closes)
        signals = volume_price_rules.evaluate(ctx)
        assert any(s.rule == "VOLUME_PRICE_DIVERGENCE_BEAR" for s in signals)

    def test_insufficient_data_returns_empty(self):
        ctx = {"kline_recent": [{"volume": 100, "close": 10}]}
        assert volume_price_rules.evaluate(ctx) == []


# ============================================
# ashare_rules: A 股特有
# ============================================
class TestAShareRules:
    def test_st_risk_detected(self):
        ctx = {"ashare_flags": {"name": "ST测试", "flags": ["ST"], "is_st": True}}
        signals = ashare_rules.evaluate(ctx)
        assert any(s.rule == "ST_STOCK_RISK" and s.direction == "BEAR" for s in signals)

    def test_limit_up_detected(self):
        ctx = {"ashare_flags": {"name": "涨停股", "flags": ["LIMIT_UP"], "change_pct": 10.0, "limit_up": True}}
        signals = ashare_rules.evaluate(ctx)
        assert any(s.rule == "LIMIT_UP_TODAY" and s.direction == "BULL" for s in signals)

    def test_limit_down_detected(self):
        ctx = {"ashare_flags": {"name": "跌停股", "flags": ["LIMIT_DOWN"], "change_pct": -10.0, "limit_down": True}}
        signals = ashare_rules.evaluate(ctx)
        assert any(s.rule == "LIMIT_DOWN_TODAY" and s.direction == "BEAR" for s in signals)

    def test_suspended_detected(self):
        ctx = {"ashare_flags": {"name": "停牌", "flags": ["SUSPENDED"], "suspended": True}}
        signals = ashare_rules.evaluate(ctx)
        assert any(s.rule == "SUSPENDED" and s.direction == "NEUTRAL" for s in signals)

    def test_empty_flags_returns_empty(self):
        assert ashare_rules.evaluate({}) == []


# ============================================
# money_flow_rules: 资金流
# ============================================
class TestMoneyFlowRules:
    def test_main_net_inflow(self):
        ctx = {"money_flow": {"main_net": 5e8, "main_net_pct": 15.0}}  # 净流入 5 亿
        signals = money_flow_rules.evaluate(ctx)
        assert any(s.rule == "MAIN_NET_INFLOW" and s.direction == "BULL" for s in signals)

    def test_main_net_outflow(self):
        ctx = {"money_flow": {"main_net": -3e8, "main_net_pct": -10.0}}  # 净流出 3 亿
        signals = money_flow_rules.evaluate(ctx)
        assert any(s.rule == "MAIN_NET_OUTFLOW" and s.direction == "BEAR" for s in signals)

    def test_main_net_trend_inflow(self):
        ctx = {
            "money_flow": {
                "main_net": 1e8,
                "recent_main_net_sum": 1e9,  # 累计净流入 10 亿
                "history": [{"main_net": 1e8}] * 5,
            }
        }
        signals = money_flow_rules.evaluate(ctx)
        assert any(s.rule == "MAIN_NET_INFLOW_TREND" and s.direction == "BULL" for s in signals)

    def test_dragon_tiger_net_buy(self):
        ctx = {"dragon_tiger": [{"net": 2e8}, {"net": 1e8}]}  # 累计净买 3 亿
        signals = money_flow_rules.evaluate(ctx)
        assert any(s.rule == "DRAGON_TIGER_NET_BUY" and s.direction == "BULL" for s in signals)

    def test_dragon_tiger_net_sell(self):
        ctx = {"dragon_tiger": [{"net": -2e8}, {"net": -1e8}]}
        signals = money_flow_rules.evaluate(ctx)
        assert any(s.rule == "DRAGON_TIGER_NET_SELL" and s.direction == "BEAR" for s in signals)

    def test_empty_money_flow_returns_empty(self):
        assert money_flow_rules.evaluate({}) == []
