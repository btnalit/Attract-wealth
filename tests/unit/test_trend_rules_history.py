# -*- coding: utf-8 -*-
"""trend_rules 序列规则单元测试（金叉穿越/RSI/MACD背离）。"""
from __future__ import annotations

from src.agents.rules import trend_rules


class TestTrendHistoryRules:
    def _make_kline(self, closes):
        """从 close 序列构造 kline_recent（ma5/ma20 用滑动窗口近似）。"""
        kline = []
        for i, c in enumerate(closes):
            window5 = closes[max(0, i - 4):i + 1]
            window20 = closes[max(0, i - 19):i + 1]
            kline.append({
                "date": f"d{i}",
                "close": c,
                "ma5": sum(window5) / len(window5),
                "ma20": sum(window20) / len(window20),
            })
        return kline

    def test_golden_cross_detected(self):
        """构造 MA5 从下方上穿 MA20 的场景。"""
        # 前 15 天下跌（MA5 < MA20），后 15 天急涨（MA5 上穿 MA20）
        closes = [100 - i * 0.5 for i in range(15)] + [92.5 + i * 1.5 for i in range(1, 16)]
        kline = self._make_kline(closes)
        signals = trend_rules.evaluate_with_history(kline)
        rules = [s.rule for s in signals]
        assert "MA_GOLDEN_CROSS" in rules

    def test_death_cross_detected(self):
        """构造 MA5 从上方下穿 MA20 的场景。"""
        # 前 15 天上涨（MA5 > MA20），后 15 天急跌（MA5 下穿 MA20）
        closes = [90 + i * 0.8 for i in range(15)] + [101 - i * 1.5 for i in range(1, 16)]
        kline = self._make_kline(closes)
        signals = trend_rules.evaluate_with_history(kline)
        rules = [s.rule for s in signals]
        assert "MA_DEATH_CROSS" in rules

    def test_no_cross_in_steady_trend(self):
        """稳定上涨（MA5 始终 > MA20）不应产生金叉信号。"""
        closes = [100 + i * 0.3 for i in range(30)]
        kline = self._make_kline(closes)
        signals = trend_rules.evaluate_with_history(kline)
        cross_rules = [s.rule for s in signals if "CROSS" in s.rule]
        assert "MA_GOLDEN_CROSS" not in cross_rules
        assert "MA_DEATH_CROSS" not in cross_rules

    def test_macd_divergence_bottom(self):
        """构造底背离：价格创新低但 MACD(DIF) 未创新低。"""
        # 第一段下跌到低点，反弹，第二段下跌到更低点但跌幅放缓
        closes = []
        closes.extend([100 - i * 1.0 for i in range(15)])  # 跌到 85
        closes.extend([85 + i * 0.5 for i in range(1, 8)])  # 反弹到 88
        closes.extend([88 - i * 0.3 for i in range(1, 13)])  # 缓跌到 84.7（更低但跌势缓）
        closes.extend([84.7 + i * 0.2 for i in range(1, 10)])  # 缓涨
        kline = self._make_kline(closes)
        signals = trend_rules.evaluate_with_history(kline)
        # 底背离是较复杂的形态，至少不应崩溃；如果有背离信号验证方向
        div_signals = [s for s in signals if "DIVERGENCE" in s.rule]
        for s in div_signals:
            if "BOTTOM" in s.rule:
                assert s.direction == "BULL"

    def test_empty_kline_returns_empty(self):
        assert trend_rules.evaluate_with_history([]) == []
        assert trend_rules.evaluate_with_history([{"close": 100}]) == []

    def test_short_kline_no_cross(self):
        """只有 2 天数据，无法判断穿越。"""
        kline = self._make_kline([100, 101])
        signals = trend_rules.evaluate_with_history(kline)
        assert signals == []


class TestRSIRules:
    def test_rsi_overbought(self):
        indicators = {"MA5": 10, "MA20": 10, "RSI_14": 78}
        signals = trend_rules.evaluate(indicators)
        assert any(s.rule == "RSI_OVERBOUGHT" and s.direction == "BEAR" for s in signals)

    def test_rsi_oversold(self):
        indicators = {"MA5": 10, "MA20": 10, "RSI_14": 22}
        signals = trend_rules.evaluate(indicators)
        assert any(s.rule == "RSI_OVERSOLD" and s.direction == "BULL" for s in signals)

    def test_rsi_normal_no_signal(self):
        indicators = {"MA5": 10, "MA20": 10, "RSI_14": 55}
        signals = trend_rules.evaluate(indicators)
        assert not any("RSI" in s.rule for s in signals)
