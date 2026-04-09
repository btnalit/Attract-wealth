from __future__ import annotations

import asyncio

from src.execution.base import OrderResult, OrderSide, OrderStatus
from src.execution.order_manager import OrderManager


class _Broker:
    channel_name = "simulation"

    def __init__(self):
        self._orders = []
        self._connected = True

    @property
    def is_connected(self):
        return self._connected

    async def get_orders(self, date=None):
        return self._orders


def test_order_sync_is_idempotent_for_same_signature(monkeypatch):
    broker = _Broker()
    manager = OrderManager(broker)  # type: ignore[arg-type]

    local_order = OrderResult(
        order_id="oid-1",
        status=OrderStatus.SUBMITTED,
        ticker="000001",
        side=OrderSide.BUY,
        price=10.0,
        quantity=100,
    )
    manager.add_active_order(local_order)

    remote_order = OrderResult(
        order_id="oid-1",
        status=OrderStatus.PARTIAL,
        ticker="000001",
        side=OrderSide.BUY,
        price=10.0,
        quantity=100,
        filled_quantity=100,
        filled_price=10.01,
    )
    broker._orders = [remote_order]

    calls = {"n": 0}

    def _mock_update(*args, **kwargs):
        calls["n"] += 1
        return {"updated": True, "reason": "ok", "status": "partial"}

    monkeypatch.setattr(
        "src.execution.order_manager.TradingLedger.update_trade_status",
        _mock_update,
    )

    asyncio.run(manager.sync_now())
    asyncio.run(manager.sync_now())

    assert calls["n"] == 1
    assert "oid-1" in manager.active_orders


def test_order_sync_tracks_by_broker_order_id_fallback(monkeypatch):
    broker = _Broker()
    manager = OrderManager(broker)  # type: ignore[arg-type]

    local_order = OrderResult(
        order_id="local-1",
        status=OrderStatus.SUBMITTED,
        ticker="000001",
        side=OrderSide.BUY,
        price=10.0,
        quantity=100,
        message="broker_order_id=88888",
    )
    manager.add_active_order(local_order)

    remote_order = OrderResult(
        order_id="88888",
        status=OrderStatus.FILLED,
        ticker="000001",
        side=OrderSide.BUY,
        price=10.0,
        quantity=100,
        filled_quantity=100,
        filled_price=10.0,
        message="broker_order_id=88888",
    )
    broker._orders = [remote_order]

    monkeypatch.setattr(
        "src.execution.order_manager.TradingLedger.update_trade_status",
        lambda *args, **kwargs: {"updated": True, "reason": "ok", "status": "filled"},
    )

    asyncio.run(manager.sync_now())

    assert local_order.status == OrderStatus.FILLED
    assert "local-1" not in manager.active_orders
