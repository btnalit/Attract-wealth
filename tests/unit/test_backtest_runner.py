from __future__ import annotations

import pytest

from src.evolution.backtest_runner import BacktestRunner


def test_backtest_runner_with_explicit_signals_produces_metrics():
    runner = BacktestRunner()
    bars = [
        {"timestamp": "2026-01-01", "close": 10.0, "signal": "BUY"},
        {"timestamp": "2026-01-02", "close": 11.0, "signal": "HOLD"},
        {"timestamp": "2026-01-03", "close": 12.0, "signal": "SELL"},
        {"timestamp": "2026-01-04", "close": 11.5, "signal": "HOLD"},
    ]
    report = runner.run(
        strategy_id="s1",
        strategy_name="test",
        strategy_version=1,
        bars=bars,
        parameters={"position_ratio": 1.0},
        start_cash=10000.0,
        lot_size=1,
        commission_rate=0.0,
        slippage_bp=0.0,
    )
    metrics = report["metrics"]
    assert metrics["trade_count"] >= 2
    assert metrics["net_pnl"] > 0
    assert 0 <= metrics["max_drawdown"] <= 1
    assert "signal_counts" in metrics


def test_backtest_runner_auto_signal_path_runs():
    runner = BacktestRunner()
    bars = [
        {"ts": "2026-01-01", "close": 10.0},
        {"ts": "2026-01-02", "close": 10.2},
        {"ts": "2026-01-03", "close": 10.5},
        {"ts": "2026-01-04", "close": 10.8},
        {"ts": "2026-01-05", "close": 11.1},
        {"ts": "2026-01-06", "close": 10.7},
    ]
    report = runner.run(
        strategy_id="s2",
        strategy_name="auto",
        strategy_version=2,
        bars=bars,
        parameters={"lookback": 2, "buy_threshold": 0.01, "sell_threshold": -0.02, "position_ratio": 0.6},
        start_cash=100000.0,
        lot_size=100,
        commission_rate=0.0003,
        slippage_bp=1.0,
    )
    assert report["summary"]["bars"] == len(bars)
    assert report["metrics"]["trade_count"] >= 1
    assert report["metrics"]["turnover"] >= 0.0


def test_backtest_runner_rejects_invalid_bars():
    runner = BacktestRunner()
    with pytest.raises(ValueError):
        runner.run(
            strategy_id="s3",
            strategy_name="bad",
            strategy_version=1,
            bars=[{"close": 10.0}],
            parameters={},
        )

    with pytest.raises(ValueError):
        runner.run(
            strategy_id="s4",
            strategy_name="bad2",
            strategy_version=1,
            bars=[{"close": 10.0}, {"close": 0}],
            parameters={},
        )
