# -*- coding: utf-8 -*-
"""calibrate_weights 脚本单元测试（合成数据，无网络依赖）。"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd


def _load_module():
    root = Path(__file__).resolve().parents[2]
    module_path = root / "scripts" / "strategy" / "calibrate_weights.py"
    spec = importlib.util.spec_from_file_location("calibrate_weights", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _synthetic_kline(n: int = 120) -> pd.DataFrame:
    """构造一段带趋势的合成 K 线，让 backtest 能跑出非空样本。"""
    dates = pd.date_range(end="2026-06-01", periods=n, freq="B")
    # 交替的上涨/下跌段，确保产生金叉死叉信号
    closes = []
    price = 10.0
    for i in range(n):
        seg = (i // 20) % 2
        price *= 1.01 if seg == 0 else 0.99
        closes.append(round(price, 3))
    return pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"),
        "open": closes,
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes],
        "close": closes,
        "volume": [1000000] * n,
    })


class TestCalibrateHelpers:
    def test_trend_rule_names_shared_constant(self):
        """共享常量 TREND_RULE_NAMES 应包含关键趋势规则。"""
        from src.agents.rules.trend_rules import TREND_RULE_NAMES
        assert "MA_GOLDEN_CROSS" in TREND_RULE_NAMES
        assert "MACD_TOP_DIVERGENCE" in TREND_RULE_NAMES
        assert "UNKNOWN_RULE" not in TREND_RULE_NAMES

    def test_hit_rates_to_analyst_maps_trend_to_technical(self):
        m = _load_module()
        rates = m._hit_rates_to_analyst({"MA_GOLDEN_CROSS": 0.7, "RSI_OVERSOLD": 0.6})
        assert abs(rates["technical"] - 0.65) < 1e-9  # avg(0.7, 0.6)
        assert rates["fundamental"] == 0.5
        assert rates["news"] == 0.5

    def test_hit_rates_to_analyst_empty_returns_neutral(self):
        m = _load_module()
        rates = m._hit_rates_to_analyst({})
        assert rates["technical"] == 0.5


class TestCalibrateFromTickers:
    def test_synthetic_kline_produces_samples(self, monkeypatch):
        """用合成 K 线替换网络抓取，验证校准流程端到端跑通。"""
        m = _load_module()
        fake_df = _synthetic_kline(120)

        # monkeypatch 抓取函数返回合成数据
        monkeypatch.setattr(m, "_fetch_kline", lambda ticker, limit=250: fake_df.copy())

        calibrated, meta = m.calibrate_from_tickers(["SYNTH"], forward_days=5)

        assert meta["sample_records"] > 0
        assert "technical" in calibrated
        assert "fundamental" in calibrated
        # 权重总和 ≈ 100
        assert 99 <= sum(calibrated.values()) <= 101

    def test_no_kline_falls_back_to_neutral(self, monkeypatch):
        """无任何 K 线时应回退到中性命中率，不抛异常。"""
        m = _load_module()
        monkeypatch.setattr(m, "_fetch_kline", lambda ticker, limit=250: pd.DataFrame())

        calibrated, meta = m.calibrate_from_tickers(["NONE"])

        assert meta["sample_records"] == 0
        assert meta["overall_hit_rate"] == 0.0
        # 中性命中率下权重比例应等于默认比例
        assert 99 <= sum(calibrated.values()) <= 101


class TestEnvWrite:
    def test_update_env_appends_new_key(self, tmp_path):
        m = _load_module()
        env = tmp_path / ".env"
        env.write_text("FOO=bar\n", encoding="utf-8")

        updated = m._update_env_file(env, '{"technical": 50}')
        assert not updated  # 是新增而非替换
        content = env.read_text(encoding="utf-8")
        assert "FOO=bar" in content
        assert 'ASHARE_ANALYST_WEIGHTS={"technical": 50}' in content

    def test_update_env_replaces_existing(self, tmp_path):
        m = _load_module()
        env = tmp_path / ".env"
        env.write_text(
            "ASHARE_ANALYST_WEIGHTS={\"old\": 1}\nFOO=bar\n", encoding="utf-8"
        )

        updated = m._update_env_file(env, '{"technical": 60}')
        assert updated
        content = env.read_text(encoding="utf-8")
        assert 'ASHARE_ANALYST_WEIGHTS={"technical": 60}' in content
        assert '{"old": 1}' not in content
        assert "FOO=bar" in content


class TestMainEntry:
    def test_main_no_ticker_returns_nonzero(self, monkeypatch, capsys):
        """无标的时以演示流程运行，返回码非 0（区分演示与真实校准）。"""
        m = _load_module()
        monkeypatch.setattr(sys, "argv", ["calibrate_weights.py"])
        rc = m.main()
        assert rc == 2  # 演示输出
        out = capsys.readouterr().out
        assert "ASHARE_ANALYST_WEIGHTS=" in out

    def test_main_with_synthetic_data_returns_zero(self, monkeypatch, capsys):
        m = _load_module()
        fake_df = _synthetic_kline(120)
        monkeypatch.setattr(m, "_fetch_kline", lambda ticker, limit=250: fake_df.copy())
        monkeypatch.setattr(sys, "argv", ["calibrate_weights.py", "--ticker", "SYNTH"])
        rc = m.main()
        assert rc == 0
        out = capsys.readouterr().out
        assert "校准后权重" in out
