from __future__ import annotations

import asyncio

from src.execution.base import OrderResult, OrderSide, OrderStatus
from src.execution.ths_ipc.broker import THSIPCBroker


def test_get_orders_can_match_without_client_order_id():
    broker = THSIPCBroker()
    broker._local_orders["ths-1"] = OrderResult(
        order_id="ths-1",
        status=OrderStatus.SUBMITTED,
        ticker="000001",
        side=OrderSide.BUY,
        price=10.0,
        quantity=100,
        message="broker_order_id=9001;status_raw=submitted",
        channel=broker.channel_name,
    )

    async def _mock_send(payload):
        assert payload["action"] == "get_orders"
        assert payload["mode"] == "full"
        return {
            "status": "success",
            "data": [
                {
                    "order_id": "9001",
                    "status": "filled",
                    "filled_quantity": 100,
                    "filled_price": 10.01,
                }
            ],
        }

    broker._send_request = _mock_send  # type: ignore[assignment]
    rows = asyncio.run(broker.get_orders())

    assert len(rows) == 1
    assert rows[0].order_id == "ths-1"
    assert rows[0].status == OrderStatus.FILLED
    assert rows[0].filled_quantity == 100


def test_get_positions_maps_ths_fields():
    broker = THSIPCBroker()

    async def _mock_send(payload):
        assert payload["action"] == "get_positions"
        return {
            "status": "success",
            "data": {
                "600638": {
                    "zqdm": "600638",
                    "gpye": 1120,
                    "kyye": 1110,
                    "cbj": 12.036,
                    "sj": 8.3,
                    "sz": 9296.0,
                }
            },
        }

    broker._send_request = _mock_send  # type: ignore[assignment]
    rows = asyncio.run(broker.get_positions())

    assert len(rows) == 1
    assert rows[0].ticker == "600638"
    assert rows[0].quantity == 1120
    assert rows[0].available == 1110
    assert rows[0].avg_cost == 12.036
    assert rows[0].current_price == 8.3
    assert rows[0].market_value == 9296.0


def test_get_balance_maps_ths_fields():
    broker = THSIPCBroker()

    async def _mock_send(payload):
        assert payload["action"] == "get_balance"
        return {
            "status": "success",
            "data": {
                "kyje": 11288.56,
                "zzc": 225895.38,
                "zsz": 214516.0,
                "djje": 90.82,
            },
        }

    broker._send_request = _mock_send  # type: ignore[assignment]
    balance = asyncio.run(broker.get_balance())

    assert balance.available_cash == 11288.56
    assert balance.total_assets == 225895.38
    assert balance.market_value == 214516.0
    assert balance.frozen_cash == 90.82


def test_get_orders_maps_fullorder_fields_and_status():
    broker = THSIPCBroker()

    async def _mock_send(payload):
        assert payload["action"] == "get_orders"
        return {
            "status": "success",
            "data": [
                {
                    "htbh": "1262365187",
                    "zqdm": "000005",
                    "cz": "卖出",
                    "wtjg": 3.04,
                    "wtsl": 100,
                    "cjsl": 20,
                    "cjjj": 3.03,
                    "bz": "部分成交",
                }
            ],
        }

    broker._send_request = _mock_send  # type: ignore[assignment]
    rows = asyncio.run(broker.get_orders())

    assert len(rows) == 1
    assert rows[0].order_id == "ths-remote-1262365187"
    assert rows[0].ticker == "000005"
    assert rows[0].side == OrderSide.SELL
    assert rows[0].price == 3.04
    assert rows[0].quantity == 100
    assert rows[0].filled_quantity == 20
    assert rows[0].filled_price == 3.03
    assert rows[0].status == OrderStatus.PARTIAL


def test_get_trade_snapshot_returns_bridge_payload():
    broker = THSIPCBroker()

    async def _mock_send(payload):
        assert payload["action"] == "get_trade_snapshot"
        return {
            "status": "success",
            "data": {"balance": {"kyje": 1000.0}, "positions": {"000001": {"gpye": 100}}},
            "meta": {"runtime": {"in_ths_api": True}},
        }

    broker._send_request = _mock_send  # type: ignore[assignment]
    snapshot = asyncio.run(broker.get_trade_snapshot())
    assert snapshot["status"] == "success"
    assert snapshot["data"]["balance"]["kyje"] == 1000.0


def test_connect_blocks_mock_runtime_by_default(monkeypatch):
    monkeypatch.delenv("THS_IPC_ALLOW_MOCK", raising=False)
    broker = THSIPCBroker()

    async def _mock_send(payload):
        assert payload["action"] == "ping"
        return {"status": "ok", "runtime": {"in_ths_api": False, "in_xiadan_api": False}}

    broker._send_request = _mock_send  # type: ignore[assignment]
    ok = asyncio.run(broker.connect())

    assert ok is False
    assert broker.is_connected is False


def test_connect_allows_mock_runtime_when_enabled(monkeypatch):
    monkeypatch.setenv("THS_IPC_ALLOW_MOCK", "true")
    broker = THSIPCBroker()

    async def _mock_send(payload):
        assert payload["action"] == "ping"
        return {"status": "ok", "runtime": {"in_ths_api": False, "in_xiadan_api": False}}

    broker._send_request = _mock_send  # type: ignore[assignment]
    ok = asyncio.run(broker.connect())

    assert ok is True
    assert broker.is_connected is True
