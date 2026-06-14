# -*- coding: utf-8 -*-
"""分析师权重校准模块单元测试。"""
from __future__ import annotations

from src.agents.rules.weights import (
    DEFAULT_WEIGHTS,
    calibrate_weights_from_backtest,
    format_weights_for_env,
    get_calibrated_weights,
)


class TestWeights:
    def test_default_weights_present(self):
        """默认权重应包含关键类别。"""
        assert "technical" in DEFAULT_WEIGHTS
        assert "fundamental" in DEFAULT_WEIGHTS

    def test_get_calibrated_weights_returns_dict(self):
        w = get_calibrated_weights()
        assert isinstance(w, dict)
        assert len(w) > 0
        assert "technical" in w

    def test_calibrate_high_hit_rate_increases_weight(self):
        """命中率高的类别权重应相对上升。"""
        base = {"technical": 50, "fundamental": 50}
        calibrated = calibrate_weights_from_backtest(
            {"technical": 0.8, "fundamental": 0.4},
            base_weights=base,
        )
        # technical 命中率 80% → factor=1.3，fundamental 40% → factor=0.9
        # 校准后 technical 应比 fundamental 占比更高
        assert calibrated["technical"] > calibrated["fundamental"]

    def test_calibrate_normalizes_to_100(self):
        calibrated = calibrate_weights_from_backtest({"technical": 0.7, "fundamental": 0.5})
        total = sum(calibrated.values())
        assert 99 <= total <= 101  # 归一化后总和约 100

    def test_calibrate_equal_rates_keeps_proportion(self):
        """命中率相同时，权重比例不变。"""
        base = {"technical": 60, "fundamental": 40}
        calibrated = calibrate_weights_from_backtest(
            {"technical": 0.6, "fundamental": 0.6},
            base_weights=base,
        )
        ratio_before = base["technical"] / base["fundamental"]
        ratio_after = calibrated["technical"] / calibrated["fundamental"]
        assert abs(ratio_before - ratio_after) < 0.1

    def test_format_weights_for_env(self):
        s = format_weights_for_env({"technical": 45.5, "fundamental": 30.0})
        assert "technical" in s
        assert isinstance(s, str)
