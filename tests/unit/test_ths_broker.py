from __future__ import annotations

import asyncio

from src.execution.base import OrderSide, OrderStatus
from src.execution.ths_broker import THSBroker


class _FakeClient:
    def __init__(self):
        self.balance = {"available_cash": "12000", "total_assets": "15000", "market_value": "2800"}
        self.position = [{"ticker": "600000", "quantity": "200", "available": "100", "avg_cost": "10.1", "market_value": "2100"}]
        self.today_entrusts = [
            {"order_id": "B1", "ticker": "600000", "side": "BUY", "status": "submitted", "price": "10.2", "quantity": "100"}
        ]
        self.exit_called = 0

    def buy(self, ticker: str, price: float, quantity: int):
        return {"entrust_no": "9001", "ticker": ticker, "price": price, "qty": quantity}

    def sell(self, ticker: str, price: float, quantity: int):
        return {"entrust_no": "9002", "ticker": ticker, "price": price, "qty": quantity}

    def cancel_entrust(self, order_id: str):
        return {"message": f"cancel success:{order_id}"}

    def exit(self):
        self.exit_called += 1


def _patch_client(monkeypatch, fake_client: _FakeClient):
    def _fake_create_client(**kwargs):
        return fake_client, {"ok": True, "reason": "connected", "broker": "ths"}

    monkeypatch.setattr("src.execution.ths_broker.create_easytrader_client", _fake_create_client)


def test_ths_broker_connect_and_snapshot(monkeypatch):
    fake_client = _FakeClient()
    _patch_client(monkeypatch, fake_client)

    broker = THSBroker(exe_path=r"D:\ths\xiadan.exe")
    assert asyncio.run(broker.connect()) is True
    assert broker.is_connected is True

    balance = asyncio.run(broker.get_balance())
    assert balance.available_cash == 12000.0
    assert balance.total_assets == 15000.0

    positions = asyncio.run(broker.get_positions())
    assert len(positions) == 1
    assert positions[0].ticker == "600000"
    assert positions[0].quantity == 200

    orders = asyncio.run(broker.get_orders())
    assert len(orders) == 1
    assert orders[0].order_id == "ths-auto-remote-B1"
    assert orders[0].status == OrderStatus.SUBMITTED


def test_ths_broker_buy_and_cancel(monkeypatch):
    fake_client = _FakeClient()
    _patch_client(monkeypatch, fake_client)

    broker = THSBroker(exe_path=r"D:\ths\xiadan.exe")
    assert asyncio.run(broker.connect()) is True

    result = asyncio.run(broker.buy("000001", 10.0, 100))
    assert result.side == OrderSide.BUY
    assert result.status == OrderStatus.SUBMITTED
    assert "broker_order_id=9001" in result.message

    assert asyncio.run(broker.cancel(result.order_id)) is True
    assert broker._local_orders[result.order_id].status == OrderStatus.CANCELLED


def test_ths_broker_disconnect_does_not_exit_client_by_default(monkeypatch):
    fake_client = _FakeClient()
    _patch_client(monkeypatch, fake_client)
    monkeypatch.delenv("THS_AUTO_CLOSE_ON_DISCONNECT", raising=False)

    broker = THSBroker(exe_path=r"D:\ths\xiadan.exe")
    assert asyncio.run(broker.connect()) is True
    asyncio.run(broker.disconnect())
    assert fake_client.exit_called == 0


def test_ths_broker_disconnect_can_exit_client_when_configured(monkeypatch):
    fake_client = _FakeClient()
    _patch_client(monkeypatch, fake_client)
    monkeypatch.setenv("THS_AUTO_CLOSE_ON_DISCONNECT", "1")

    broker = THSBroker(exe_path=r"D:\ths\xiadan.exe")
    assert asyncio.run(broker.connect()) is True
    asyncio.run(broker.disconnect())
    assert fake_client.exit_called == 1
