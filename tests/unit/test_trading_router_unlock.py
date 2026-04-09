from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.routers.trading import router


class _Service:
    def unlock_reconciliation_block(self, reason: str = "manual", operator: str = "api", **kwargs):
        return {
            "was_blocked": True,
            "reason": reason,
            "operator": operator,
            "extra": kwargs,
            "guard": {"blocked": False},
        }


def _build_client() -> TestClient:
    app = FastAPI()
    app.state.trading_service = _Service()
    app.include_router(router, prefix="/api/trading")
    return TestClient(app)


def test_unlock_requires_token_when_configured(monkeypatch):
    monkeypatch.setenv("RECON_UNLOCK_TOKEN", "secret-token")
    client = _build_client()
    resp = client.post("/api/trading/reconcile/unlock", json={"reason": "unit", "operator": "test"})
    assert resp.status_code == 403
    body = resp.json()
    assert body["ok"] is False
    assert body["code"] == "UNAUTHORIZED_UNLOCK"


def test_unlock_succeeds_with_valid_token(monkeypatch):
    monkeypatch.setenv("RECON_UNLOCK_TOKEN", "secret-token")
    client = _build_client()
    resp = client.post(
        "/api/trading/reconcile/unlock",
        json={"reason": "unit", "operator": "test"},
        headers={"X-Recon-Unlock-Token": "secret-token"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["code"] == "RECON_UNLOCKED"
