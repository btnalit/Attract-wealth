from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.core.trading_service import TradingService
from src.execution.base import AccountBalance, BaseBroker, OrderResult, OrderSide, OrderStatus
from src.routers import system, trading


class _EventEngineStub:
    scheduler = None

    def get_watchlists(self):
        return ["000001"]

    def get_autopilot_state(self):
        return {"template": "balanced", "execute_orders": True}


class _BuyVM:
    async def run(self, ticker: str, initial_context=None):
        ctx = initial_context or {}
        ctx["portfolio"] = {"balance": 1_000_000.0, "positions": {}}
        ctx["realtime"] = {"price": 10.0}
        return {
            "session_id": "it-session",
            "ticker": ticker,
            "messages": [],
            "current_agent": "trader",
            "decision": "BUY",
            "confidence": 91.0,
            "analysis_reports": {},
            "context": ctx,
            "trading_decision": {
                "action": "BUY",
                "percentage": 10,
                "reason": "integration-regression",
                "confidence": 91,
            },
        }


class _ChainBroker(BaseBroker):
    channel_name = "simulation"

    def __init__(self):
        self._connected = False
        self._seq = 0
        self._remote_orders: dict[str, OrderResult] = {}

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> bool:
        self._connected = True
        return True

    async def disconnect(self):
        self._connected = False

    async def buy(self, ticker: str, price: float, quantity: int, **kwargs) -> OrderResult:
        self._seq += 1
        local_order_id = f"sim-{self._seq}"

        remote = OrderResult(
            order_id=local_order_id,
            status=OrderStatus.FILLED,
            ticker=ticker,
            side=OrderSide.BUY,
            price=price,
            filled_price=price,
            quantity=quantity,
            filled_quantity=quantity,
            amount=price * quantity,
            channel=self.channel_name,
        )
        self._remote_orders[local_order_id] = remote

        return OrderResult(
            order_id=local_order_id,
            status=OrderStatus.SUBMITTED,
            ticker=ticker,
            side=OrderSide.BUY,
            price=price,
            quantity=quantity,
            channel=self.channel_name,
            message=f"broker_order_id={local_order_id}",
        )

    async def sell(self, ticker: str, price: float, quantity: int, **kwargs) -> OrderResult:
        self._seq += 1
        local_order_id = f"sim-{self._seq}"
        return OrderResult(
            order_id=local_order_id,
            status=OrderStatus.SUBMITTED,
            ticker=ticker,
            side=OrderSide.SELL,
            price=price,
            quantity=quantity,
            channel=self.channel_name,
            message=f"broker_order_id={local_order_id}",
        )

    async def cancel(self, order_id: str) -> bool:
        return True

    async def get_positions(self):
        return []

    async def get_balance(self) -> AccountBalance:
        return AccountBalance(
            total_assets=1_000_000.0,
            available_cash=1_000_000.0,
            frozen_cash=0.0,
            market_value=0.0,
            total_pnl=0.0,
            daily_pnl=0.0,
        )

    async def get_orders(self, date: str | None = None):
        _ = date
        return list(self._remote_orders.values())


def _patch_ledger(monkeypatch):
    from src.core import trading_service as ts_module
    from src.execution import order_manager as om_module

    monkeypatch.setattr(ts_module.TradingLedger, "record_trade", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(ts_module.TradingLedger, "record_analysis", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(ts_module.TradingLedger, "record_entry", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(ts_module.TradingLedger, "record_decision_evidence", staticmethod(lambda *args, **kwargs: "evidence"))
    monkeypatch.setattr(
        om_module.TradingLedger,
        "update_trade_status",
        staticmethod(lambda *args, **kwargs: {"updated": True, "status": "filled"}),
    )


def _build_test_client(service: TradingService) -> TestClient:
    app = FastAPI()
    app.state.trading_service = service
    app.state.event_engine = _EventEngineStub()
    app.include_router(trading.router, prefix="/api/trading")
    app.include_router(system.router, prefix="/api/system")
    return TestClient(app)


def test_regression_chain_simulation_sync_reconcile_unlock(monkeypatch):
    _patch_ledger(monkeypatch)
    monkeypatch.setenv("RECON_UNLOCK_TOKEN", "unlock-secret")

    broker = _ChainBroker()
    service = TradingService(trading_channel="simulation", vm=_BuyVM(), broker=broker)
    service._china_data_disabled = True
    client = _build_test_client(service)

    execute_resp = client.post("/api/trading/execute", json={"ticker": "000001"})
    assert execute_resp.status_code == 200
    execute_body = execute_resp.json()
    assert execute_body["ok"] is True
    assert execute_body["code"] == "EXECUTE_OK"
    order_id = execute_body["data"]["order"]["order_id"]

    active_before = client.get("/api/trading/orders/active")
    assert active_before.status_code == 200
    active_orders_before = active_before.json()["data"]
    assert any(order["order_id"] == order_id for order in active_orders_before)

    sync_resp = client.post("/api/trading/orders/sync")
    assert sync_resp.status_code == 200
    sync_body = sync_resp.json()
    assert sync_body["ok"] is True
    assert sync_body["code"] == "ORDERS_SYNC_OK"
    assert sync_body["data"]["stats"]["updated"] >= 1
    assert sync_body["data"]["stats"]["removed"] >= 1

    active_after = client.get("/api/trading/orders/active")
    assert active_after.status_code == 200
    active_orders_after = active_after.json()["data"]
    assert all(order["order_id"] != order_id for order in active_orders_after)

    async def _mock_recon_block(initial_cash=None):
        _ = initial_cash
        return {
            "status": "mismatch",
            "issues_count": 2,
            "issues": [{"key": "cash"}],
            "alert_level": "critical",
            "action": "block",
            "code": "RECON_BLOCK",
        }

    service.reconciliation_engine.run = _mock_recon_block  # type: ignore[assignment]

    recon_resp = client.post("/api/trading/reconcile", json={"initial_cash": 1_000_000.0})
    assert recon_resp.status_code == 409
    recon_body = recon_resp.json()
    assert recon_body["ok"] is False
    assert recon_body["code"] == "RECON_BLOCK"

    guard_blocked = client.get("/api/system/reconciliation/guard")
    assert guard_blocked.status_code == 200
    guard_blocked_body = guard_blocked.json()
    assert guard_blocked_body["data"]["blocked"] is True

    blocked_execute_resp = client.post("/api/trading/execute", json={"ticker": "000001"})
    assert blocked_execute_resp.status_code == 409
    blocked_execute_body = blocked_execute_resp.json()
    assert blocked_execute_body["ok"] is False
    assert blocked_execute_body["code"] == "RECON_BLOCKED"

    unlock_resp = client.post(
        "/api/trading/reconcile/unlock",
        json={"reason": "integration_chain", "operator": "pytest"},
        headers={"X-Recon-Unlock-Token": "unlock-secret"},
    )
    assert unlock_resp.status_code == 200
    unlock_body = unlock_resp.json()
    assert unlock_body["ok"] is True
    assert unlock_body["code"] == "RECON_UNLOCKED"
    assert unlock_body["data"]["guard"]["blocked"] is False

    guard_unblocked = client.get("/api/system/reconciliation/guard")
    assert guard_unblocked.status_code == 200
    guard_unblocked_body = guard_unblocked.json()
    assert guard_unblocked_body["data"]["blocked"] is False

    execute_after_unlock = client.post("/api/trading/execute", json={"ticker": "000001"})
    assert execute_after_unlock.status_code == 200
    assert execute_after_unlock.json()["code"] == "EXECUTE_OK"

    dataflow_metrics_resp = client.get("/api/system/dataflow/metrics")
    assert dataflow_metrics_resp.status_code == 200
    metrics_body = dataflow_metrics_resp.json()
    assert metrics_body["ok"] is True
    assert "quality" in metrics_body["data"]
    assert "summary" in metrics_body["data"]
    assert "retry_rate" in metrics_body["data"]["summary"]
    assert "rate_limited_rate" in metrics_body["data"]["summary"]

    dataflow_quality_resp = client.get("/api/system/dataflow/quality")
    assert dataflow_quality_resp.status_code == 200
    quality_body = dataflow_quality_resp.json()
    assert quality_body["ok"] is True
    assert "quality" in quality_body["data"]
    assert "summary" in quality_body["data"]
    assert "tuning" in quality_body["data"]
    assert "retry_rate" in quality_body["data"]["summary"]
    assert "rate_limited_rate" in quality_body["data"]["summary"]

    dataflow_tuning_resp = client.get("/api/system/dataflow/tuning")
    assert dataflow_tuning_resp.status_code == 200
    dataflow_tuning_body = dataflow_tuning_resp.json()
    assert dataflow_tuning_body["ok"] is True
    assert "summary" in dataflow_tuning_body["data"]
    assert "quality" in dataflow_tuning_body["data"]
    assert "tuning" in dataflow_tuning_body["data"]

    runtime_resp = client.get("/api/system/runtime")
    assert runtime_resp.status_code == 200
    runtime_body = runtime_resp.json()
    assert runtime_body["ok"] is True
    assert "dataflow_summary" in runtime_body["data"]
    assert "retry_rate" in runtime_body["data"]["dataflow_summary"]
    assert "rate_limited_rate" in runtime_body["data"]["dataflow_summary"]
    assert "dataflow_tuning" in runtime_body["data"]
    assert "action" in runtime_body["data"]["dataflow_tuning"]
    assert "llm_usage_summary" in runtime_body["data"]
    assert "llm_runtime" in runtime_body["data"]

    llm_metrics_resp = client.get("/api/system/llm/metrics")
    assert llm_metrics_resp.status_code == 200
    llm_metrics_body = llm_metrics_resp.json()
    assert llm_metrics_body["ok"] is True
    assert "usage_summary" in llm_metrics_body["data"]
    assert "runtime" in llm_metrics_body["data"]

    evidence_resp = client.get("/api/system/audit/evidence")
    assert evidence_resp.status_code == 200
    evidence_body = evidence_resp.json()
    assert evidence_body["ok"] is True
    assert "items" in evidence_body["data"]
    assert "count" in evidence_body["data"]
