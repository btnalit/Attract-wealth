from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.routers.monitor import router


class _Broker:
    is_connected = True


class _RiskGate:
    MAX_DAILY_LOSS_RATIO = 0.05
    MAX_POSITION_CONCENTRATION = 0.30

    def __init__(self) -> None:
        self._paused = False
        self._pause_reason = ""

    @property
    def is_paused(self) -> bool:
        return self._paused

    def reset_daily(self) -> None:
        self._paused = False
        self._pause_reason = ""

    def get_metrics(self) -> dict:
        return {
            "pass_rate": 0.9,
            "rule_hits": {"ORDER_FREQUENCY": 3},
        }

    def get_recent_alerts(self, limit: int = 200) -> list[dict]:
        _ = limit
        return [
            {"rule": "DAILY_LOSS_LIMIT", "context": {"value": 0.03}},
            {"rule": "POSITION_CONCENTRATION", "context": {"value": 0.12}},
        ]


class _Service:
    def __init__(self) -> None:
        self.channel = "ths_auto"
        self.broker = _Broker()
        self.risk_gate = _RiskGate()
        self._china_data_disabled = True


def _build_client() -> TestClient:
    app = FastAPI()
    app.state.trading_service = _Service()
    app.include_router(router, prefix="/api/v1/monitor")
    return TestClient(app)


def test_monitor_status_marks_ths_auto_as_online():
    client = _build_client()
    resp = client.get("/api/v1/monitor/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    channels = body["data"]
    assert channels[0]["name"] == "THS IPC"
    assert channels[0]["status"] == "online"


def test_monitor_risk_metrics_and_toggle_flow():
    client = _build_client()

    risk_resp = client.get("/api/v1/monitor/risk")
    assert risk_resp.status_code == 200
    risk_data = risk_resp.json()["data"]
    assert risk_data["max_drawdown_current"] == 0.03
    assert risk_data["position_limit_current"] == 0.12
    assert risk_data["trade_frequency_day"] == 3
    assert risk_data["api_rate_limit_percent"] == 10.0
    assert risk_data["switches"]["auto_stop"] is True

    toggle_resp = client.post("/api/v1/monitor/risk/toggle", json={"name": "auto_stop", "enabled": False})
    assert toggle_resp.status_code == 200
    assert toggle_resp.json()["data"]["switches"]["auto_stop"] is False

    pause_resp = client.post("/api/v1/monitor/risk/toggle", json={"name": "global_pause", "enabled": True})
    assert pause_resp.status_code == 200
    assert pause_resp.json()["data"]["risk_paused"] is True


def test_monitor_audit_reads_from_trading_ledger(monkeypatch):
    client = _build_client()

    def _fake_list_ledger_entries(*, limit: int, category: str = "", action: str = "", status: str = "", trace_id: str = ""):
        _ = (limit, category, action, status, trace_id)
        return [
            {
                "timestamp": 1710000000.0,
                "level": "ERROR",
                "category": "RISK",
                "detail": "risk rejected order",
                "action": "DIRECT_ORDER_RISK_REJECTED",
                "status": "rejected",
                "metadata": {"ticker": "600000"},
            },
            {
                "timestamp": 1710000001.0,
                "level": "INFO",
                "category": "SYSTEM",
                "detail": "heartbeat ok",
                "action": "HEARTBEAT",
                "status": "success",
                "metadata": {},
            },
        ]

    monkeypatch.setattr("src.services.monitor_service.TradingLedger.list_ledger_entries", _fake_list_ledger_entries)

    resp = client.get("/api/v1/monitor/audit", params={"limit": 2, "offset": 0})
    assert resp.status_code == 200
    logs = resp.json()["data"]
    assert len(logs) == 2
    assert logs[0]["severity"] == "High"
    assert logs[0]["type"] == "Risk"
    assert logs[1]["severity"] == "Low"


def test_monitor_data_health_returns_compatibility_fields(monkeypatch):
    client = _build_client()

    def _fake_catalog(self):
        _ = self
        return {
            "current_provider": "akshare",
            "current_provider_display_name": "AkShare",
            "providers": [
                {
                    "name": "akshare",
                    "display_name": "AkShare",
                    "enabled": True,
                    "current": True,
                    "priority": 10,
                    "requests": 20,
                    "success": 15,
                    "failure": 5,
                    "empty": 0,
                    "retry_success": 0,
                    "rate_limited": 0,
                    "error_rate": 0.25,
                    "empty_rate": 0.0,
                    "retry_rate": 0.0,
                    "rate_limited_rate": 0.0,
                    "last_error_code": "",
                    "last_error": "",
                    "last_latency_ms": 21.5,
                    "last_success_ts": 0.0,
                    "last_failure_ts": 0.0,
                }
            ],
            "summary": {"requests_total": 20},
            "quality": {"alert_level": "none"},
            "tuning": {"action": "none"},
            "runtime_config": {},
        }

    class _Provider:
        @staticmethod
        def get_metrics() -> dict:
            return {
                "last_fields": ["price", "volume"],
            }

    monkeypatch.setattr("src.services.monitor_service.DataflowService.list_provider_catalog", _fake_catalog)
    monkeypatch.setattr(
        "src.services.monitor_service.DataflowService.get_provider_instance",
        lambda self, name=None: _Provider(),  # noqa: ARG005
    )

    resp = client.get("/api/v1/monitor/data-health")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "online"
    assert data["last_fields"] == ["price", "volume"]
    assert data["recent_fields"] == ["price", "volume"]
    assert data["success_rate"] == 0.75
    assert data["success_rate_pct"] == 75.0
    assert data["success_rate_ratio"] == 0.75


def test_monitor_quote_returns_amount_turnover_and_volume_aliases(monkeypatch):
    client = _build_client()

    monkeypatch.setattr(
        "src.services.monitor_service.DataflowService.get_provider_instance",
        lambda self, name=None: object(),  # noqa: ARG005
    )
    monkeypatch.setattr(
        "src.services.monitor_service.DataflowService.get_realtime_quote",
        lambda self, ticker: {  # noqa: ARG005
            "price": 10.5,
            "change_pct": 1.25,
            "amount": 123456.0,
            "volume_chg": 2.2,
            "name": "Test Symbol",
        },
    )

    resp = client.get("/api/v1/monitor/quote/600000")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["ticker"] == "600000"
    assert data["amount"] == 123456.0
    assert data["turnover"] == 123456.0
    assert data["volume_chg"] == 2.2
    assert data["volume"] == 2.2
