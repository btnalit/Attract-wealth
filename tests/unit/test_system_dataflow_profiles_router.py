from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.core.dataflow_profiles import DATAFLOW_PROFILE_ENV_KEYS
from src.routers.system import router


def _build_client() -> TestClient:
    app = FastAPI()
    app.state.startup_preflight = {
        "ok": True,
        "summary": {"total": 1, "failed": 0, "critical_failed": 0, "warning_failed": 0},
        "checks": [],
    }
    app.include_router(router, prefix="/api/system")
    return TestClient(app)


def _capture_env() -> dict[str, str | None]:
    return {key: os.environ.get(key) for key in DATAFLOW_PROFILE_ENV_KEYS}


def _restore_env(snapshot: dict[str, str | None]) -> None:
    for key, value in snapshot.items():
        if value is None:
            os.environ.pop(key, None)
            continue
        os.environ[key] = value


def test_dataflow_profiles_endpoint_returns_catalog():
    client = _build_client()
    resp = client.get("/api/system/dataflow/profiles")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["code"] in {"DATAFLOW_PROFILES_OK", "DATAFLOW_PROFILES_DEGRADED"}
    assert "profiles" in body["data"]
    assert "ths_live_safe" in body["data"]["profiles"]
    assert body["data"]["profiles"]["ths_live_safe"]["version"]
    assert "current_env" in body["data"]


def test_dataflow_profile_apply_rejects_invalid_profile():
    client = _build_client()
    resp = client.post("/api/system/dataflow/profile/apply", json={"profile": "not-exists", "persist": False})
    assert resp.status_code == 400
    body = resp.json()
    assert body["ok"] is False
    assert body["code"] == "INVALID_ORDER_REQUEST"


def test_dataflow_profile_apply_success():
    client = _build_client()
    backup = _capture_env()
    try:
        resp = client.post("/api/system/dataflow/profile/apply", json={"profile": "ths_paper_default", "persist": False})
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["code"] in {"DATAFLOW_PROFILE_APPLIED", "DATAFLOW_PROFILE_APPLIED_DEGRADED"}
        assert body["data"]["profile"] == "ths_paper_default"
        assert body["data"]["profile_version"]
        assert body["data"]["applied_env"]["DATA_PROVIDER_RATE_LIMIT_PER_MINUTE"] == "120"
        assert "runtime_config" in body["data"]
    finally:
        _restore_env(backup)
