from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from src.execution.base import OrderResult, OrderSide, OrderStatus
from src.execution.base import AccountBalance


def _load_module():
    root = Path(__file__).resolve().parents[2]
    module_path = root / "scripts" / "smoke" / "live_channel_smoke.py"
    spec = importlib.util.spec_from_file_location("live_channel_smoke", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_json_safe_handles_dataclass_with_datetime():
    module = _load_module()
    order = OrderResult(
        order_id="o1",
        status=OrderStatus.SUBMITTED,
        ticker="000001",
        side=OrderSide.BUY,
        price=10.0,
        quantity=100,
    )
    payload = module._json_safe(order)
    assert isinstance(payload, dict)
    assert isinstance(payload.get("timestamp"), str)


def test_resolve_reconcile_initial_cash_prefers_explicit_value():
    module = _load_module()
    balance = AccountBalance(total_assets=123.0, available_cash=45.0)
    result = module._resolve_reconcile_initial_cash(
        channel="ths_ipc",
        balance=balance,
        explicit_initial_cash=888.0,
    )
    assert result == 888.0


def test_resolve_reconcile_initial_cash_uses_broker_snapshot():
    module = _load_module()
    balance = AccountBalance(total_assets=321.0, available_cash=45.0)
    result = module._resolve_reconcile_initial_cash(
        channel="ths_ipc",
        balance=balance,
        explicit_initial_cash=None,
    )
    assert result == 321.0


def test_resolve_reconcile_initial_cash_uses_zero_for_live_empty_balance():
    module = _load_module()
    balance = AccountBalance(total_assets=0.0, available_cash=0.0)
    result = module._resolve_reconcile_initial_cash(
        channel="ths_ipc",
        balance=balance,
        explicit_initial_cash=None,
    )
    assert result == 0.0


def test_bootstrap_simulation_broker_from_ledger_applies_snapshot(monkeypatch):
    module = _load_module()

    class _Broker:
        channel_name = "simulation"

        def __init__(self):
            self.loaded: dict[str, object] = {}

        def load_portfolio_snapshot(self, *, cash: float, positions: dict[str, int], reset_orders: bool = False):
            self.loaded = {
                "cash": cash,
                "positions": positions,
                "reset_orders": reset_orders,
            }

    monkeypatch.setattr(
        "src.core.trading_ledger.TradingLedger.build_portfolio_snapshot",
        lambda initial_cash=1_000_000.0, channel="": {"cash": 888_000.0, "positions": {"000001": 300}},
    )

    broker = _Broker()
    meta = module._bootstrap_simulation_broker_from_ledger(broker=broker, initial_cash=1_000_000.0)
    assert meta["applied"] is True
    assert broker.loaded["cash"] == 888_000.0
    assert broker.loaded["positions"] == {"000001": 300}
    assert broker.loaded["reset_orders"] is True


def test_bootstrap_simulation_broker_from_ledger_respects_disable_flag(monkeypatch):
    module = _load_module()
    monkeypatch.setenv("SMOKE_SIM_RECON_BOOTSTRAP", "false")

    class _Broker:
        channel_name = "simulation"

        def load_portfolio_snapshot(self, *, cash: float, positions: dict[str, int], reset_orders: bool = False):
            raise AssertionError("should not be called when bootstrap disabled")

    meta = module._bootstrap_simulation_broker_from_ledger(broker=_Broker(), initial_cash=1_000_000.0)
    assert meta["applied"] is False
    assert meta["reason"] == "disabled"
