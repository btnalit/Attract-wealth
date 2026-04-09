from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.routers.trading import router


class _Service:
    async def get_trade_snapshot(self, include_channel_raw: bool = True):
        return {
            "channel": "simulation",
            "broker_connected": True,
            "balance": {"available_cash": 1000000.0},
            "positions": [],
            "orders": [],
            "reconciliation_guard": {"blocked": False},
            "counts": {"positions": 0, "orders": 0},
            "channel_raw": {"enabled": include_channel_raw},
        }


def _build_client() -> TestClient:
    app = FastAPI()
    app.state.trading_service = _Service()
    app.include_router(router, prefix="/api/trading")
    return TestClient(app)


def test_trade_snapshot_endpoint_success():
    client = _build_client()
    resp = client.get("/api/trading/snapshot", params={"include_channel_raw": "true"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["code"] == "SNAPSHOT_OK"
    assert body["data"]["channel"] == "simulation"
    assert body["data"]["channel_raw"]["enabled"] is True
