# -*- coding: utf-8 -*-
"""板块联动规则引擎单元测试。"""
from __future__ import annotations

from src.agents.rules import sector_rules


class TestSectorRules:
    def test_bullish_resonance(self):
        ctx = {
            'realtime': {'change_pct': 3.5},
            'sector_info': {'industry': '银行', 'sector_performance': {'sector_name': '银行', 'sector_change_pct': 2.5}},
        }
        signals = sector_rules.evaluate(ctx)
        assert any(s.rule == 'SECTOR_BULLISH_RESONANCE' and s.direction == 'BULL' for s in signals)

    def test_bearish_resonance(self):
        ctx = {
            'realtime': {'change_pct': -3.0},
            'sector_info': {'industry': '地产', 'sector_performance': {'sector_name': '地产', 'sector_change_pct': -2.5}},
        }
        signals = sector_rules.evaluate(ctx)
        assert any(s.rule == 'SECTOR_BEARISH_RESONANCE' and s.direction == 'BEAR' for s in signals)

    def test_divergence_up(self):
        ctx = {
            'realtime': {'change_pct': 3.0},
            'sector_info': {'industry': '钢铁', 'sector_performance': {'sector_name': '钢铁', 'sector_change_pct': -2.0}},
        }
        signals = sector_rules.evaluate(ctx)
        assert any(s.rule == 'SECTOR_DIVERGENCE_UP' and s.direction == 'BULL' for s in signals)

    def test_sector_strong_trend(self):
        ctx = {
            'realtime': {'change_pct': 1.0},
            'sector_info': {'industry': '新能源', 'sector_performance': {'sector_name': '新能源', 'sector_change_pct': 4.0}},
        }
        signals = sector_rules.evaluate(ctx)
        assert any(s.rule == 'SECTOR_STRONG_TREND' and s.direction == 'BULL' for s in signals)

    def test_sector_leader_strong(self):
        ctx = {
            'realtime': {'change_pct': 1.0},
            'sector_info': {
                'industry': '半导体',
                'sector_performance': {'sector_name': '半导体', 'sector_change_pct': 1.5, 'leader_stock': '中芯国际', 'leader_change_pct': 8.0},
            },
        }
        signals = sector_rules.evaluate(ctx)
        assert any(s.rule == 'SECTOR_LEADER_STRONG' and s.direction == 'BULL' for s in signals)

    def test_empty_sector_returns_empty(self):
        assert sector_rules.evaluate({}) == []

    def test_no_sector_performance_returns_empty(self):
        ctx = {'sector_info': {'industry': '银行'}}
        assert sector_rules.evaluate(ctx) == []
