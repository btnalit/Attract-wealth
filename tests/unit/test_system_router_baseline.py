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


def test_system_config_and_wechat_routes_delegate_to_service(monkeypatch):
    from src.routers import system as system_router

    captured: dict = {}

    class _FakeSystemConfigService:
        def load_runtime_config(self):
            captured["loaded"] = True
            return {
                "tushare_token": "ts-token",
                "wechat_webhook": "https://example.invalid/webhook",
                "dingtalk_secret": "dt-secret",
            }

        def save_runtime_config(self, config: dict):
            captured["saved"] = dict(config)
            return {
                "tushare_token": "ts-token-2",
                "wechat_webhook": "https://example.invalid/webhook-2",
                "dingtalk_secret": "dt-secret-2",
            }

        def send_wechat_test(self, webhook_url: str):
            captured["wechat_webhook_url"] = webhook_url
            return True

    fake_service = _FakeSystemConfigService()
    monkeypatch.setattr(system_router, "_get_system_config_service", lambda request: fake_service)

    client = _build_client()
    get_resp = client.get("/api/system/config")
    assert get_resp.status_code == 200
    get_body = get_resp.json()
    assert get_body["ok"] is True
    assert get_body["data"]["wechat_webhook"] == "https://example.invalid/webhook"
    assert captured["loaded"] is True

    put_resp = client.put("/api/system/config", json={"wechat_webhook": "https://example.invalid/new"})
    assert put_resp.status_code == 200
    put_body = put_resp.json()
    assert put_body["ok"] is True
    assert captured["saved"]["wechat_webhook"] == "https://example.invalid/new"
    assert put_body["data"]["config"]["wechat_webhook"] == "https://example.invalid/webhook-2"

    test_resp = client.post(
        "/api/system/notification/test/wechat",
        json={"webhook_url": "https://example.invalid/ping", "channel": "wechat"},
    )
    assert test_resp.status_code == 200
    assert captured["wechat_webhook_url"] == "https://example.invalid/ping"


def test_dataflow_quality_feedback_endpoints(monkeypatch):
    from src.routers import system as system_router

    class _FakeDataflowService:
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

    fake_service = _FakeDataflowService()
    monkeypatch.setattr(system_router, "_get_dataflow_service", lambda request: fake_service)

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


def test_dataflow_provider_catalog_and_switch(monkeypatch):
    from src.routers import system as system_router

    class _FakeDataflowService:
        def list_provider_catalog(self):
            return {
                "current_provider": "akshare",
                "current_provider_display_name": "AkShare",
                "providers": [
                    {"name": "akshare", "display_name": "AkShare", "enabled": True, "current": True, "priority": 10},
                    {"name": "baostock", "display_name": "BaoStock", "enabled": True, "current": False, "priority": 20},
                ],
                "summary": {"requests_total": 0},
                "quality": {"alert_level": "none"},
                "tuning": {"action": "none"},
                "runtime_config": {},
            }

        def switch_provider(self, *, provider_name: str, persist: bool = False, system_store=None):  # noqa: ARG002
            if provider_name not in {"akshare", "baostock"}:
                raise ValueError("provider is required")
            return {
                "applied_provider": provider_name,
                "persisted": bool(persist),
                "current_provider": provider_name,
                "current_provider_display_name": "BaoStock" if provider_name == "baostock" else "AkShare",
                "providers": [],
                "summary": {},
                "quality": {},
                "tuning": {},
                "runtime_config": {},
            }

    fake_service = _FakeDataflowService()
    monkeypatch.setattr(system_router, "_get_dataflow_service", lambda request: fake_service)

    client = _build_client()

    list_resp = client.get("/api/system/dataflow/providers")
    assert list_resp.status_code == 200
    list_body = list_resp.json()
    assert list_body["ok"] is True
    assert list_body["code"] == "DATAFLOW_PROVIDERS_OK"
    assert list_body["data"]["current_provider"] == "akshare"

    switch_resp = client.post("/api/system/dataflow/provider/use", json={"provider": "baostock", "persist": False})
    assert switch_resp.status_code == 200
    switch_body = switch_resp.json()
    assert switch_body["ok"] is True
    assert switch_body["code"] == "DATAFLOW_PROVIDER_SWITCHED"
    assert switch_body["data"]["applied_provider"] == "baostock"

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


def test_llm_config_legacy_alias_is_backward_compatible():
    client = _build_client()

    legacy_get_resp = client.get("/api/system/llm-config")
    assert legacy_get_resp.status_code == 200
    legacy_get_body = legacy_get_resp.json()
    assert legacy_get_body["ok"] is True
    assert legacy_get_body["code"] == "LLM_CONFIG_COMPAT_OK"
    assert "base_url" in legacy_get_body["data"]
    assert "runtime_config" in legacy_get_body["data"]

    legacy_put_resp = client.put(
        "/api/system/llm-config",
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
    assert legacy_put_resp.status_code == 200
    legacy_put_body = legacy_put_resp.json()
    assert legacy_put_body["ok"] is True
    assert legacy_put_body["code"] == "LLM_CONFIG_COMPAT_UPDATED"
    assert legacy_put_body["data"]["has_api_key"] is True
    assert "runtime_config" in legacy_put_body["data"]


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
