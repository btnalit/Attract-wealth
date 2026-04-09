from __future__ import annotations

import asyncio

from src.execution.base import AccountBalance, Position
from src.execution.reconciliation import ReconciliationEngine


class _Broker:
    channel_name = "simulation"

    async def get_balance(self):
        return AccountBalance(total_assets=1_000_000.0, available_cash=900_000.0, market_value=100_000.0)

    async def get_positions(self):
        return [Position(ticker="000001", quantity=1000)]


def test_reconciliation_detects_mismatch(monkeypatch):
    broker = _Broker()
    engine = ReconciliationEngine(broker, cash_tolerance=1.0, quantity_tolerance=0)  # type: ignore[arg-type]

    monkeypatch.setattr(
        "src.execution.reconciliation.TradingLedger.build_portfolio_snapshot",
        lambda initial_cash=1_000_000.0: {"cash": 950_000.0, "positions": {"000001": 800}},
    )
    monkeypatch.setattr("src.execution.reconciliation.TradingLedger.record_reconciliation", lambda report: None)
    monkeypatch.setattr("src.execution.reconciliation.TradingLedger.record_entry", lambda entry: None)

    result = asyncio.run(engine.run(initial_cash=1_000_000.0))
    assert result["status"] == "mismatch"
    assert result["issues_count"] >= 1


def test_reconciliation_warn_level(monkeypatch):
    monkeypatch.setenv("RECON_CASH_WARN", "1000")
    monkeypatch.setenv("RECON_CASH_BLOCK", "10000")

    broker = _Broker()
    engine = ReconciliationEngine(broker, cash_tolerance=1.0, quantity_tolerance=0)  # type: ignore[arg-type]

    monkeypatch.setattr(
        "src.execution.reconciliation.TradingLedger.build_portfolio_snapshot",
        lambda initial_cash=1_000_000.0: {"cash": 898_500.0, "positions": {"000001": 1000}},
    )
    monkeypatch.setattr("src.execution.reconciliation.TradingLedger.record_reconciliation", lambda report: None)
    monkeypatch.setattr("src.execution.reconciliation.TradingLedger.record_entry", lambda entry: None)

    result = asyncio.run(engine.run(initial_cash=1_000_000.0))
    assert result["status"] == "mismatch"
    assert result["alert_level"] == "warn"
    assert result["action"] == "record"
    assert result["code"] == "RECON_WARN"


def test_reconciliation_block_level(monkeypatch):
    monkeypatch.setenv("RECON_CASH_WARN", "1000")
    monkeypatch.setenv("RECON_CASH_BLOCK", "10000")

    broker = _Broker()
    engine = ReconciliationEngine(broker, cash_tolerance=1.0, quantity_tolerance=0)  # type: ignore[arg-type]

    monkeypatch.setattr(
        "src.execution.reconciliation.TradingLedger.build_portfolio_snapshot",
        lambda initial_cash=1_000_000.0: {"cash": 870_000.0, "positions": {"000001": 1000}},
    )
    monkeypatch.setattr("src.execution.reconciliation.TradingLedger.record_reconciliation", lambda report: None)
    monkeypatch.setattr("src.execution.reconciliation.TradingLedger.record_entry", lambda entry: None)

    result = asyncio.run(engine.run(initial_cash=1_000_000.0))
    assert result["status"] == "mismatch"
    assert result["alert_level"] == "critical"
    assert result["action"] == "block"
    assert result["code"] == "RECON_BLOCK"
