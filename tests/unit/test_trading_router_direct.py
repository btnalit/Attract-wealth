from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.routers.trading import router


class _Service:
    async def place_direct_order(self, **kwargs):
        self.last_kwargs = kwargs
        return {
            "request_id": "req-001",
            "idempotency_key": "idem-001",
            "channel": "simulation",
            "risk_check": {"passed": True, "reason": "ok"},
            "order": {"status": "submitted", "order_id": "local-001"},
            "trace": {
                "request_id": "req-001",
                "idempotency_key": "idem-001",
                "channel": "simulation",
                "client_order_id": "co-001",
                "local_order_id": "local-001",
                "broker_order_id": "BRK-001",
                "status": "submitted",
            },
            "idempotent_replay": False,
        }

    def get_direct_order_trace(self, **kwargs):
        if kwargs.get("idempotency_key") == "missing":
            return None
        return {
            "request_id": "req-001",
            "idempotency_key": "idem-001",
            "channel": "simulation",
            "client_order_id": "co-001",
            "local_order_id": "local-001",
            "broker_order_id": "BRK-001",
            "status": "submitted",
            "trade_status": "submitted",
        }

    async def cancel_active_orders(self, reason: str = "manual"):
        self.cancel_reason = reason
        return {
            "channel": "simulation",
            "reason": reason,
            "requested": 2,
            "cancelled": 2,
            "failed": 0,
            "items": [],
        }

    async def switch_channel(self, target_channel: str, reconnect: bool = True):
        self.switch_target_channel = target_channel
        self.switch_reconnect = reconnect
        return {
            "changed": True,
            "requested_channel": target_channel,
            "previous_channel": "ths_auto",
            "active_channel": target_channel,
            "broker_connected": True,
        }


def _build_client() -> TestClient:
    app = FastAPI()
    app.state.trading_service = _Service()
    app.include_router(router, prefix="/api/trading")
    return TestClient(app)


def test_direct_order_endpoint_success():
    client = _build_client()
    resp = client.post(
        "/api/trading/orders/direct",
        json={
            "ticker": "000001",
            "side": "BUY",
            "quantity": 100,
            "price": 10,
            "order_type": "limit",
            "idempotency_key": "idem-001",
            "client_order_id": "co-001",
            "channel": "simulation",
            "memo": "unit",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["code"] == "DIRECT_ORDER_ACCEPTED"
    assert body["data"]["trace"]["broker_order_id"] == "BRK-001"


def test_direct_order_endpoint_accepts_qty_type_alias():
    client = _build_client()
    resp = client.post(
        "/api/trading/orders/direct",
        json={
            "ticker": "000001",
            "side": "BUY",
            "qty": 100,
            "price": 10,
            "type": "limit",
            "idempotency_key": "idem-qty-001",
            "client_order_id": "co-qty-001",
            "channel": "simulation",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["code"] == "DIRECT_ORDER_ACCEPTED"


def test_direct_order_endpoint_accepts_camel_case_payload():
    client = _build_client()
    resp = client.post(
        "/api/trading/orders/direct",
        json={
            "ticker": "000001",
            "side": "BUY",
            "quantity": 100,
            "price": 10,
            "orderType": "limit",
            "idempotencyKey": "idem-camel-001",
            "clientOrderId": "co-camel-001",
            "requestId": "req-camel-001",
            "traceId": "trace-camel-001",
            "manualConfirm": True,
            "manualConfirmToken": "token-001",
            "channel": "simulation",
            "memo": "camel",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["code"] == "DIRECT_ORDER_ACCEPTED"


def test_direct_order_endpoint_rejects_quantity_qty_mismatch():
    client = _build_client()
    resp = client.post(
        "/api/trading/orders/direct",
        json={
            "ticker": "000001",
            "side": "BUY",
            "quantity": 100,
            "qty": 200,
            "price": 10,
            "order_type": "limit",
            "idempotency_key": "idem-mismatch-001",
            "channel": "simulation",
        },
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["ok"] is False
    assert body["code"] == "INVALID_ORDER_REQUEST"


def test_direct_order_endpoint_requires_quantity_or_qty():
    client = _build_client()
    resp = client.post(
        "/api/trading/orders/direct",
        json={
            "ticker": "000001",
            "side": "BUY",
            "price": 10,
            "order_type": "limit",
            "idempotency_key": "idem-missing-qty-001",
            "channel": "simulation",
        },
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["ok"] is False
    assert body["code"] == "INVALID_ORDER_REQUEST"


def test_order_trace_requires_filter():
    client = _build_client()
    resp = client.get("/api/trading/orders/trace")
    assert resp.status_code == 400
    body = resp.json()
    assert body["ok"] is False
    assert body["code"] == "INVALID_ORDER_REQUEST"


def test_order_trace_not_found():
    client = _build_client()
    resp = client.get("/api/trading/orders/trace", params={"idempotency_key": "missing"})
    assert resp.status_code == 404
    body = resp.json()
    assert body["ok"] is False
    assert body["code"] == "ORDER_TRACE_NOT_FOUND"


def test_order_trace_accepts_trace_id_filter():
    client = _build_client()
    resp = client.get("/api/trading/orders/trace", params={"trace_id": "trace-001"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["code"] == "ORDER_TRACE_OK"


def test_cancel_all_orders_endpoint_success():
    client = _build_client()
    resp = client.post("/api/trading/orders/cancel-all", json={"reason": "unit-test"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["code"] == "ORDERS_CANCEL_ALL_OK"
    assert body["data"]["cancelled"] == 2
    assert body["data"]["failed"] == 0


def test_switch_trading_channel_endpoint_success():
    client = _build_client()
    resp = client.post("/api/trading/channel/switch", json={"channel": "simulation", "reconnect": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["code"] == "TRADING_CHANNEL_SWITCHED"
    assert body["data"]["requested_channel"] == "simulation"
    assert body["data"]["active_channel"] == "simulation"
