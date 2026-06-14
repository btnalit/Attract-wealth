# -*- coding: utf-8 -*-
"""P1-2：LLM 评分区间约束（rule_score ± band 锚点）单元测试。"""
from __future__ import annotations

import os

import pytest

from src.agents.analysts.base import (
    BaseAnalyst,
    _score_clamp_band,
)


class _ConcreteAnalyst(BaseAnalyst):
    """可实例化的 BaseAnalyst 子类（用于测试静态方法）。"""

    analyst_name = "Test_Analyst"

    async def analyze(self, state):  # noqa: ANN001, D401
        raise NotImplementedError


# ===== _clamp_score_to_anchor 静态方法 =====
class TestClampScoreToAnchor:
    def test_no_signals_no_clamp(self):
        """无规则信号时不约束（LLM 自由发挥）。"""
        score, clamped = BaseAnalyst._clamp_score_to_anchor(
            95.0, anchor=50.0, has_signals=False
        )
        assert score == 95.0
        assert clamped is False

    def test_within_band_not_clamped(self):
        """LLM 分在锚点 ± band 内不夹断。"""
        score, clamped = BaseAnalyst._clamp_score_to_anchor(
            60.0, anchor=55.0, has_signals=True
        )
        assert score == 60.0
        assert clamped is False

    def test_above_band_clamped_down(self):
        """LLM 分高于锚点 + band 被夹断到上界。"""
        score, clamped = BaseAnalyst._clamp_score_to_anchor(
            90.0, anchor=55.0, has_signals=True
        )
        assert score == 70.0  # 55 + 15
        assert clamped is True

    def test_below_band_clamped_up(self):
        """LLM 分低于锚点 - band 被夹断到下界。"""
        score, clamped = BaseAnalyst._clamp_score_to_anchor(
            20.0, anchor=55.0, has_signals=True
        )
        assert score == 40.0  # 55 - 15
        assert clamped is True

    def test_clamp_respects_zero_floor(self):
        """锚点很低时，下界不应低于 0；LLM 分低于下界才夹断。"""
        # anchor=10, band=15 → lo=max(0,-5)=0, hi=min(100,25)=25
        # LLM 分 5 >= lo(0)，不夹断
        score, clamped = BaseAnalyst._clamp_score_to_anchor(
            5.0, anchor=10.0, has_signals=True
        )
        assert score == 5.0
        assert clamped is False
        # LLM 分 30 > hi(25)，夹断到 25
        score, clamped = BaseAnalyst._clamp_score_to_anchor(
            30.0, anchor=10.0, has_signals=True
        )
        assert score == 25.0
        assert clamped is True

    def test_clamp_respects_hundred_ceiling(self):
        """锚点很高时，上界不应超过 100。"""
        # anchor=95, band=15 → lo=80, hi=min(100,110)=100
        # LLM 分 99 在 [80,100] 内，不夹断
        score, clamped = BaseAnalyst._clamp_score_to_anchor(
            99.0, anchor=95.0, has_signals=True
        )
        assert score == 99.0
        assert clamped is False
        # LLM 分 75 < lo(80)，夹断到 80
        score, clamped = BaseAnalyst._clamp_score_to_anchor(
            75.0, anchor=95.0, has_signals=True
        )
        assert score == 80.0
        assert clamped is True

    def test_band_zero_disables_clamp(self, monkeypatch):
        """band=0 时完全关闭约束。"""
        monkeypatch.setenv("ASHARE_LLM_SCORE_BAND", "0")
        score, clamped = BaseAnalyst._clamp_score_to_anchor(
            99.0, anchor=50.0, has_signals=True
        )
        assert score == 99.0
        assert clamped is False


# ===== 环境变量配置 =====
class TestScoreClampBandEnv:
    def test_default_band_is_15(self, monkeypatch):
        monkeypatch.delenv("ASHARE_LLM_SCORE_BAND", raising=False)
        assert _score_clamp_band() == 15.0

    def test_custom_band(self, monkeypatch):
        monkeypatch.setenv("ASHARE_LLM_SCORE_BAND", "8")
        assert _score_clamp_band() == 8.0

    def test_negative_band_treated_as_disabled(self, monkeypatch):
        """负值视为关闭（max(0, val)）。"""
        monkeypatch.setenv("ASHARE_LLM_SCORE_BAND", "-5")
        assert _score_clamp_band() == 0.0

    def test_invalid_band_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("ASHARE_LLM_SCORE_BAND", "not-a-number")
        assert _score_clamp_band() == 15.0


# ===== _compute_rule_fallback_score（锚点计算）=====
class TestRuleFallbackScore:
    def test_empty_signals_is_neutral(self):
        assert BaseAnalyst._compute_rule_fallback_score([]) == 50.0

    def test_all_bull_raises_above_50(self):
        sigs = [
            {"direction": "BULL", "strength": 80},
            {"direction": "BULL", "strength": 60},
        ]
        # bias * strength 平均 = (80 + 60)/2 = 70 → 50 + 70/2 = 85
        assert BaseAnalyst._compute_rule_fallback_score(sigs) == 85.0

    def test_all_bear_lowers_below_50(self):
        sigs = [
            {"direction": "BEAR", "strength": 80},
            {"direction": "BEAR", "strength": 60},
        ]
        assert BaseAnalyst._compute_rule_fallback_score(sigs) == 15.0

    def test_balanced_is_neutral(self):
        sigs = [
            {"direction": "BULL", "strength": 70},
            {"direction": "BEAR", "strength": 70},
        ]
        # 70 + (-70) = 0, avg 0 → 50
        assert BaseAnalyst._compute_rule_fallback_score(sigs) == 50.0


# ===== 端到端：模拟 LLM 返回越界分，验证夹断 =====
class TestClampIntegration:
    """通过模拟 _ask_llm_for_report 的 LLM 调用验证夹断生效。"""

    @pytest.mark.asyncio
    async def test_llm_score_above_anchor_gets_clamped(self, monkeypatch):
        analyst = _ConcreteAnalyst()

        # 模拟 LLM 返回 92 分
        class _FakeLLM:
            async def chat_simple(self, *a, **kw):  # noqa: ANN001, ANN002
                return '{"score": 92, "stance": "Bullish", "summary": "x", "key_factors": ["a"]}'

        analyst.llm = _FakeLLM()

        # 单个 BULL@60 信号 → 锚点 = 50 + 60/2 = 80，band=15 → 上界 95
        # LLM 返回 92 在 [65, 95] 内，不夹断；改用更高分测试夹断
        signals = [{"rule": "MA_GOLDEN_CROSS", "direction": "BULL", "strength": 60,
                    "category": "trend", "description": "金叉"}]
        report = await analyst._ask_llm_for_report(
            ticker="000001", context="test", system_prompt="sys",
            signals=signals,
        )
        # 92 在 [65,95] 内 → 不夹断
        assert report.llm_raw_score == 92.0
        assert report.score == 92.0
        assert report.score_clamped is False

    @pytest.mark.asyncio
    async def test_llm_score_outside_anchor_clamped(self, monkeypatch):
        """LLM 分明确超出锚点±band 时被夹断。"""
        analyst = _ConcreteAnalyst()

        class _FakeLLM:
            async def chat_simple(self, *a, **kw):  # noqa: ANN001, ANN002
                return '{"score": 99, "stance": "Bullish", "summary": "x", "key_factors": []}'

        analyst.llm = _FakeLLM()
        # 锚点 80，band=15 → 上界 95，LLM 返回 99 被夹断到 95
        signals = [{"rule": "MA_GOLDEN_CROSS", "direction": "BULL", "strength": 60,
                    "category": "trend", "description": "金叉"}]
        report = await analyst._ask_llm_for_report(
            ticker="000001", context="test", system_prompt="sys",
            signals=signals,
        )
        assert report.llm_raw_score == 99.0
        assert report.score == 95.0  # 夹断到 80+15
        assert report.score_clamped is True
        assert report.rule_anchor_score == 80.0

    @pytest.mark.asyncio
    async def test_llm_score_within_band_not_clamped(self, monkeypatch):
        analyst = _ConcreteAnalyst()

        class _FakeLLM:
            async def chat_simple(self, *a, **kw):  # noqa: ANN001, ANN002
                return '{"score": 70, "stance": "Bullish", "summary": "x", "key_factors": []}'

        analyst.llm = _FakeLLM()
        # 锚点 80，70 在 [65,95] 内，不夹断
        signals = [{"rule": "MA_GOLDEN_CROSS", "direction": "BULL", "strength": 60,
                    "category": "trend", "description": "金叉"}]
        report = await analyst._ask_llm_for_report(
            ticker="000001", context="test", system_prompt="sys",
            signals=signals,
        )
        assert report.llm_raw_score == 70.0
        assert report.score == 70.0
        assert report.score_clamped is False

    @pytest.mark.asyncio
    async def test_no_signals_no_clamp(self):
        analyst = _ConcreteAnalyst()

        class _FakeLLM:
            async def chat_simple(self, *a, **kw):  # noqa: ANN001, ANN002
                return '{"score": 95, "stance": "Bullish", "summary": "x", "key_factors": []}'

        analyst.llm = _FakeLLM()
        # 无规则信号 → 不夹断
        report = await analyst._ask_llm_for_report(
            ticker="000001", context="test", system_prompt="sys",
        )
        assert report.score == 95.0
        assert report.score_clamped is False
        assert report.rule_anchor_score is None
