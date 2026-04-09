from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.routers.system import router


class _FakeBridgeRuntime:
    def __init__(self):
        self.state = {"ready": False, "message": "init", "stopped": False}

    def start(self, *, channel: str, allow_disabled: bool = False):
        self.state = {
            "ready": channel == "ths_ipc",
            "message": "bridge started and ready" if channel == "ths_ipc" else f"channel={channel}, skip",
            "channel": channel,
            "allow_disabled": allow_disabled,
            "stopped": False,
        }
        return dict(self.state)

    def stop(self, *, force: bool = False, reason: str = "shutdown"):
        self.state = {
            **self.state,
            "ready": False,
            "message": "stopped",
            "stopped": True,
            "force": force,
            "shutdown_reason": reason,
        }
        return dict(self.state)


class _FakeTradingService:
    def __init__(self):
        self.broker = type("Broker", (), {"is_connected": True})()
        self._llm_config = {
            "provider_name": "custom",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-chat",
            "quick_model": "deepseek-chat",
            "deep_model": "deepseek-reasoner",
            "timeout_s": 120.0,
            "max_tokens": 4096,
            "temperature": 0.7,
            "has_api_key": False,
            "api_key_masked": "",
        }

    def get_runtime_state(self):
        return {
            "channel": "simulation",
            "broker_connected": True,
            "risk": {"max_position_ratio": 0.2},
            "degrade_policy": {"policy_version": "test"},
            "budget_recovery_guard": {
                "active": False,
                "metrics": {
                    "activation_count": 3,
                    "release_count": 3,
                    "auto_recovery_success_count": 3,
                    "recovery_success_rate": 1.0,
                    "avg_recovery_duration_s": 0.25,
                },
            },
            "budget_recovery_metrics": {
                "activation_count": 3,
                "release_count": 3,
                "auto_recovery_success_count": 3,
                "recovery_success_rate": 1.0,
                "avg_recovery_duration_s": 0.25,
            },
            "dataflow_summary": {},
            "dataflow": {},
            "dataflow_tuning": {},
            "llm_usage_summary": {},
            "llm_runtime": {},
            "reconciliation_blocked": False,
            "reconciliation_block_reason": {},
            "calendar": {"today": "2026-04-08"},
        }

    def get_llm_runtime_config(self):
        return dict(self._llm_config)

    def update_llm_runtime_config(self, config: dict, *, operator: str = "api"):  # noqa: ARG002
        merged = dict(config)
        merged["has_api_key"] = bool(merged.get("api_key", ""))
        merged["api_key_masked"] = "***" if merged["has_api_key"] else ""
        self._llm_config.update(merged)
        return dict(self._llm_config)


class _FakeEventEngine:
    scheduler = object()

    def get_watchlists(self):
        return ["000001"]

    def get_autopilot_state(self):
        return {"running": False}


def _build_client() -> TestClient:
    app = FastAPI()
    app.state.startup_preflight = {
        "ok": True,
        "summary": {"total": 1, "failed": 0, "critical_failed": 0, "warning_failed": 0},
        "checks": [],
    }
    app.state.ths_bridge_runtime = _FakeBridgeRuntime()
    app.state.ths_bridge = {"ready": False, "message": "init"}
    app.state.trading_service = _FakeTradingService()
    app.state.event_engine = _FakeEventEngine()
    app.include_router(router, prefix="/api/system")
    return TestClient(app)


def test_error_codes_api_returns_catalog():
    client = _build_client()
    resp = client.get("/api/system/error-codes")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["code"] == "ERROR_CODES_OK"
    assert "INTERNAL_ERROR" in body["data"]["items"]


def test_preflight_api_returns_cached_report():
    client = _build_client()
    resp = client.get("/api/system/preflight")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["code"] == "PREFLIGHT_OK"
    assert body["data"]["ok"] is True


def test_ths_bridge_start_stop_and_state_api():
    client = _build_client()

    state_resp = client.get("/api/system/ths-bridge")
    assert state_resp.status_code == 200
    assert state_resp.json()["data"]["ths_bridge"]["ready"] is False

    start_resp = client.post(
        "/api/system/ths-bridge/start",
        json={"channel": "ths_ipc", "restart": False, "allow_disabled": True},
    )
    assert start_resp.status_code == 200
    start_body = start_resp.json()
    assert start_body["ok"] is True
    assert start_body["code"] == "THS_BRIDGE_STARTED"
    assert start_body["data"]["ths_bridge"]["ready"] is True

    stop_resp = client.post("/api/system/ths-bridge/stop", json={"force": True, "reason": "unit-test"})
    assert stop_resp.status_code == 200
    stop_body = stop_resp.json()
    assert stop_body["ok"] is True
    assert stop_body["code"] == "THS_BRIDGE_STOPPED"
    assert stop_body["data"]["ths_bridge"]["stopped"] is True


def test_audit_evidence_filters_are_passed(monkeypatch):
    captured: dict = {}

    def _fake_list_decision_evidence(**kwargs):
        captured.update(kwargs)
        return [{"id": "ev-1", "request_id": kwargs.get("request_id", ""), "degraded": True}]

    from src.routers import system as system_router

    monkeypatch.setattr(system_router.TradingLedger, "list_decision_evidence", staticmethod(_fake_list_decision_evidence))
    client = _build_client()
    resp = client.get(
        "/api/system/audit/evidence",
        params={
            "limit": 10,
            "ticker": "000001",
            "session_id": "s1",
            "phase": "execute",
            "request_id": "req-1",
            "degraded_only": "true",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["count"] == 1
    assert captured["phase"] == "execute"
    assert captured["request_id"] == "req-1"
    assert captured["degraded_only"] is True


def test_runtime_includes_budget_recovery_metrics():
    client = _build_client()
    resp = client.get("/api/system/runtime")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["budget_recovery_metrics"]["activation_count"] == 3
    assert data["budget_recovery_metrics"]["recovery_success_rate"] == 1.0


def test_dataflow_quality_feedback_endpoints(monkeypatch):
    from src.dataflows import source_manager as source_manager_module

    class _FakeDataManager:
        def __init__(self):
            self.feedback_events = []

        def get_metrics(self):
            return {
                "summary": {"quality_alert_level": "warn"},
                "quality": {"alert_level": "warn", "event_id": "dq-1"},
                "quality_event": {"event_id": "dq-1", "new_event": True},
                "quality_feedback": {"feedback_total": len(self.feedback_events), "precision": 0.0},
                "quality_events": [],
                "tuning": {},
                "runtime_config": {},
            }

        def get_quality_feedback_metrics(self):
            return {"feedback_total": len(self.feedback_events), "precision": 0.5}

        def list_quality_events(self, limit: int = 50):  # noqa: ARG002
            return list(self.feedback_events)

        def record_quality_feedback(self, *, label: str, event_id: str = "", source: str = "api", note: str = ""):
            self.feedback_events.append(
                {"label": label, "event_id": event_id, "source": source, "note": note}
            )
            return {"feedback_total": len(self.feedback_events), "precision": 1.0}

    fake_manager = _FakeDataManager()
    monkeypatch.setattr(source_manager_module, "data_manager", fake_manager)

    client = _build_client()
    quality_resp = client.get("/api/system/dataflow/quality")
    assert quality_resp.status_code == 200
    quality_body = quality_resp.json()
    assert quality_body["ok"] is True
    assert "quality_feedback" in quality_body["data"]

    post_resp = client.post(
        "/api/system/dataflow/quality/feedback",
        json={
            "label": "true_positive",
            "event_id": "dq-1",
            "source": "unit-test",
            "note": "looks good",
        },
    )
    assert post_resp.status_code == 200
    post_body = post_resp.json()
    assert post_body["ok"] is True
    assert post_body["data"]["metrics"]["feedback_total"] == 1

    get_resp = client.get("/api/system/dataflow/quality/feedback")
    assert get_resp.status_code == 200
    get_body = get_resp.json()
    assert get_body["ok"] is True
    assert get_body["data"]["metrics"]["feedback_total"] == 1


def test_llm_config_get_and_put():
    client = _build_client()

    get_resp = client.get("/api/system/llm/config")
    assert get_resp.status_code == 200
    get_body = get_resp.json()
    assert get_body["ok"] is True
    assert "config" in get_body["data"]

    put_resp = client.put(
        "/api/system/llm/config",
        json={
            "provider_name": "deepseek",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-chat",
            "quick_model": "deepseek-chat",
            "deep_model": "deepseek-reasoner",
            "timeout_s": 120,
            "max_tokens": 4096,
            "temperature": 0.6,
            "api_key": "sk-test-1234567890",
        },
    )
    assert put_resp.status_code == 200
    put_body = put_resp.json()
    assert put_body["ok"] is True
    assert put_body["code"] == "LLM_CONFIG_UPDATED"
    assert put_body["data"]["config"]["has_api_key"] is True
    assert "api_key_masked" in put_body["data"]["config"]


def test_llm_config_test_endpoint(monkeypatch):
    from src.routers import system as system_router

    class _FakeCompletionResponse:
        def __init__(self):
            self.choices = [type("Choice", (), {"message": type("Msg", (), {"content": "pong"})()})()]
            self.usage = type("Usage", (), {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})()

    class _FakeCompletions:
        @staticmethod
        async def create(**kwargs):  # noqa: ARG002
            return _FakeCompletionResponse()

    class _FakeAsyncOpenAI:
        def __init__(self, **kwargs):  # noqa: ARG002
            self.chat = type("Chat", (), {"completions": _FakeCompletions()})()

    monkeypatch.setattr(system_router, "AsyncOpenAI", _FakeAsyncOpenAI)

    client = _build_client()
    resp = client.post(
        "/api/system/llm/config/test",
        json={
            "provider_name": "deepseek",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-chat",
            "api_key": "sk-test-1234567890",
            "timeout_s": 60,
            "max_tokens": 128,
            "temperature": 0.1,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["code"] == "LLM_CONFIG_TEST_OK"
    assert body["data"]["sample"] == "pong"
