from __future__ import annotations

import asyncio

from src.execution.base import AccountBalance, OrderResult, OrderSide, OrderStatus, Position
from src.execution.qmt_broker import QMTBroker


def _build_broker() -> QMTBroker:
    return QMTBroker(account_id="test-account", mini_qmt_path=r"D:\qmt")


def test_qmt_check_health_reflects_connection_state():
    broker = _build_broker()
    health = broker.check_health()
    assert health["channel"] == "qmt"
    assert health["status"] == "dead"
    assert health["is_connected"] is False
    assert "xt_available" in health

    broker._is_connected = True
    broker._local_orders["qmt-1"] = OrderResult(
        order_id="qmt-1",
        status=OrderStatus.SUBMITTED,
        ticker="000001",
        side=OrderSide.BUY,
        price=10.0,
        quantity=100,
        channel=broker.channel_name,
    )
    health_connected = broker.check_health()
    assert health_connected["status"] == "active"
    assert health_connected["is_connected"] is True
    assert health_connected["local_orders"] == 1


def test_qmt_trade_snapshot_returns_error_when_not_connected():
    broker = _build_broker()
    broker._local_orders["qmt-1"] = OrderResult(
        order_id="qmt-1",
        status=OrderStatus.SUBMITTED,
        ticker="000001",
        side=OrderSide.BUY,
        price=10.0,
        quantity=100,
        channel=broker.channel_name,
    )

    snapshot = asyncio.run(broker.get_trade_snapshot())
    assert snapshot["status"] == "error"
    assert snapshot["message"] == "broker not connected"
    assert snapshot["meta"]["connected"] is False
    assert len(snapshot["data"]["orders"]) == 1


def test_qmt_trade_snapshot_success_path(monkeypatch):
    broker = _build_broker()
    broker._is_connected = True

    async def _mock_get_balance():
        return AccountBalance(total_assets=200000.0, available_cash=120000.0, market_value=80000.0)

    async def _mock_get_positions():
        return [
            Position(
                ticker="600000",
                quantity=1000,
                available=1000,
                avg_cost=10.0,
                current_price=10.5,
                market_value=10500.0,
            )
        ]

    async def _mock_get_orders(date: str | None = None):  # noqa: ARG001
        return [
            OrderResult(
                order_id="qmt-2",
                status=OrderStatus.SUBMITTED,
                ticker="600000",
                side=OrderSide.BUY,
                price=10.5,
                quantity=100,
                channel=broker.channel_name,
            )
        ]

    monkeypatch.setattr(broker, "get_balance", _mock_get_balance)
    monkeypatch.setattr(broker, "get_positions", _mock_get_positions)
    monkeypatch.setattr(broker, "get_orders", _mock_get_orders)

    snapshot = asyncio.run(broker.get_trade_snapshot())
    assert snapshot["status"] == "success"
    assert snapshot["meta"]["channel"] == "qmt"
    assert snapshot["data"]["summary"]["positions_count"] == 1
    assert snapshot["data"]["summary"]["orders_count"] == 1
    assert snapshot["data"]["summary"]["total_assets"] == 200000.0
