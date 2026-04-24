from __future__ import annotations

import pytest

from src.core.errors import TradingServiceError
from src.core.trading_service import TradingService
from src.execution.base import AccountBalance, BaseBroker, OrderResult, OrderSide, OrderStatus


class FakeBroker(BaseBroker):
    channel_name = "simulation"

    def __init__(self):
        self._connected = False
        self.executed = False
        self.new_day_called = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> bool:
        self._connected = True
        return True

    async def disconnect(self):
        self._connected = False

    async def buy(self, ticker: str, price: float, quantity: int, **kwargs) -> OrderResult:
        self.executed = True
        return OrderResult(
            order_id="test-order",
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

    async def sell(self, ticker: str, price: float, quantity: int, **kwargs) -> OrderResult:
        self.executed = True
        return OrderResult(
            order_id="test-order",
            status=OrderStatus.FILLED,
            ticker=ticker,
            side=OrderSide.SELL,
            price=price,
            filled_price=price,
            quantity=quantity,
            filled_quantity=quantity,
            amount=price * quantity,
            channel=self.channel_name,
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
        return []

    def check_health(self) -> dict:
        return {
            "name": "fake-broker",
            "channel": self.channel_name,
            "status": "active" if self._connected else "dead",
            "is_connected": self._connected,
        }

    async def get_trade_snapshot(self) -> dict:
        return {
            "status": "success",
            "data": {"orders": []},
            "meta": {"channel": self.channel_name},
        }

    def new_day(self):
        self.new_day_called = True


class HoldVM:
    async def run(self, ticker: str, initial_context=None):
        ctx = initial_context or {}
        ctx["portfolio"] = {"balance": 1_000_000.0, "positions": {}}
        ctx["realtime"] = {"price": 10.0}
        return {
            "session_id": "s1",
            "ticker": ticker,
            "messages": [],
            "current_agent": "trader",
            "decision": "HOLD",
            "confidence": 10.0,
            "analysis_reports": {},
            "context": ctx,
            "trading_decision": {"action": "HOLD", "percentage": 0, "reason": "no-op", "confidence": 10},
        }


class BuyVM:
    async def run(self, ticker: str, initial_context=None):
        ctx = initial_context or {}
        ctx["portfolio"] = {"balance": 1_000_000.0, "positions": {}}
        ctx["realtime"] = {"price": 10.0}
        return {
            "session_id": "s2",
            "ticker": ticker,
            "messages": [],
            "current_agent": "trader",
            "decision": "BUY",
            "confidence": 88.0,
            "analysis_reports": {},
            "context": ctx,
            "trading_decision": {"action": "BUY", "percentage": 10, "reason": "test buy", "confidence": 88},
        }


class DegradeVM:
    async def run(self, ticker: str, initial_context=None):
        ctx = initial_context or {}
        ctx["portfolio"] = {"balance": 1_000_000.0, "positions": {}}
        ctx["realtime"] = {"price": 0.0}
        ctx["news_sentiment"] = {"status": "error_llm", "sentiment_score": 50.0}
        return {
            "session_id": "s3",
            "ticker": ticker,
            "messages": [],
            "current_agent": "trader",
            "decision": "BUY",
            "confidence": 76.0,
            "analysis_reports": {},
            "context": ctx,
            "trading_decision": {"action": "BUY", "percentage": 20, "reason": "test degrade", "confidence": 76},
        }


class WarnOnlyVM:
    async def run(self, ticker: str, initial_context=None):
        ctx = initial_context or {}
        ctx["portfolio"] = {"balance": 1_000_000.0, "positions": {}}
        ctx["realtime"] = {"price": 10.0}
        ctx["news_sentiment"] = {"status": "ok", "sentiment_score": 50.0}
        ctx["llm_runtime"] = {"latency_exceeded_count": 1, "last_flags": ["latency_exceeded"]}
        ctx["llm_usage_summary"] = {"cost_usd": 0.0}
        return {
            "session_id": "s4",
            "ticker": ticker,
            "messages": [],
            "current_agent": "trader",
            "decision": "BUY",
            "confidence": 79.0,
            "analysis_reports": {},
            "context": ctx,
            "trading_decision": {"action": "BUY", "percentage": 10, "reason": "warn-only test", "confidence": 79},
        }


class BudgetForceHoldVM:
    async def run(self, ticker: str, initial_context=None):
        ctx = initial_context or {}
        ctx["portfolio"] = {"balance": 1_000_000.0, "positions": {}}
        ctx["realtime"] = {"price": 10.0}
        ctx["news_sentiment"] = {"status": "ok", "sentiment_score": 50.0}
        ctx["llm_usage_summary"] = {"cost_usd": 1.2}
        ctx["llm_runtime"] = {"last_flags": []}
        return {
            "session_id": "s5",
            "ticker": ticker,
            "messages": [],
            "current_agent": "trader",
            "decision": "BUY",
            "confidence": 80.0,
            "analysis_reports": {},
            "context": ctx,
            "trading_decision": {"action": "BUY", "percentage": 10, "reason": "budget test", "confidence": 80},
        }


class BudgetRecoverVM:
    async def run(self, ticker: str, initial_context=None):
        ctx = initial_context or {}
        ctx["portfolio"] = {"balance": 1_000_000.0, "positions": {}}
        ctx["realtime"] = {"price": 10.0}
        ctx["news_sentiment"] = {"status": "ok", "sentiment_score": 50.0}
        ctx["llm_usage_summary"] = {"cost_usd": 0.6}
        ctx["llm_runtime"] = {"last_flags": []}
        return {
            "session_id": "s6",
            "ticker": ticker,
            "messages": [],
            "current_agent": "trader",
            "decision": "BUY",
            "confidence": 80.0,
            "analysis_reports": {},
            "context": ctx,
            "trading_decision": {"action": "BUY", "percentage": 10, "reason": "budget recover", "confidence": 80},
        }


def _patch_ledger(monkeypatch):
    from src.core import trading_service as ts_module

    monkeypatch.setattr(ts_module.TradingLedger, "record_trade", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(ts_module.TradingLedger, "record_analysis", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(ts_module.TradingLedger, "record_entry", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(ts_module.TradingLedger, "record_decision_evidence", staticmethod(lambda *args, **kwargs: "evidence"))


def test_execute_hold_returns_no_order(monkeypatch):
    _patch_ledger(monkeypatch)
    service = TradingService(trading_channel="simulation", vm=HoldVM(), broker=FakeBroker())
    service._china_data_disabled = True

    import asyncio

    result = asyncio.run(service.execute("000001"))
    assert result["order"] is None
    assert result["decision"] == "HOLD"


def test_execute_buy_places_order(monkeypatch):
    _patch_ledger(monkeypatch)
    broker = FakeBroker()
    service = TradingService(trading_channel="simulation", vm=BuyVM(), broker=broker)
    service._china_data_disabled = True

    import asyncio

    result = asyncio.run(service.execute("000001"))
    assert result["order"] is not None
    assert result["order"]["status"] in {"filled", "submitted"}
    assert broker.executed is True


def test_execute_force_hold_on_degraded_context(monkeypatch):
    _patch_ledger(monkeypatch)
    broker = FakeBroker()
    service = TradingService(trading_channel="simulation", vm=DegradeVM(), broker=broker)
    service._china_data_disabled = True

    import asyncio

    result = asyncio.run(service.execute("000001"))
    assert result["order"] is None
    assert result["decision"] == "HOLD"
    assert broker.executed is False
    assert "realtime_price_unavailable" in result["state"]["degrade_flags"]
    assert result["state"]["degrade_policy"]["policy_version"]
    assert result["state"]["degrade_policy"]["should_degrade"] is True


def test_execute_warn_only_degrade_does_not_force_hold(monkeypatch):
    _patch_ledger(monkeypatch)
    monkeypatch.setenv("TRADE_DEGRADE_ENABLED_RULES", "llm_latency_exceeded")
    monkeypatch.setenv("TRADE_DEGRADE_LLM_LATENCY_ACTION", "warn_only")
    broker = FakeBroker()
    service = TradingService(trading_channel="simulation", vm=WarnOnlyVM(), broker=broker)
    service._china_data_disabled = True

    import asyncio

    result = asyncio.run(service.execute("000001"))
    assert result["order"] is not None
    assert result["decision"] == "BUY"
    assert result["state"]["degrade_policy"]["recommended_action"] == "warn_only"
    assert "llm_latency_exceeded" in result["state"]["degrade_warnings"]
    assert result["state"]["degrade_flags"] == []
    assert broker.executed is True


def test_execute_budget_exceeded_force_hold(monkeypatch):
    _patch_ledger(monkeypatch)
    monkeypatch.setenv("TRADE_DEGRADE_ENABLED_RULES", "llm_daily_budget_exceeded")
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "1.0")
    monkeypatch.setenv("TRADE_DEGRADE_LLM_BUDGET_ACTION", "force_hold")
    broker = FakeBroker()
    service = TradingService(trading_channel="simulation", vm=BudgetForceHoldVM(), broker=broker)
    service._china_data_disabled = True

    import asyncio

    result = asyncio.run(service.execute("000001"))
    assert result["order"] is None
    assert result["decision"] == "HOLD"
    assert "llm_daily_budget_exceeded" in result["state"]["degrade_flags"]
    assert result["state"]["degrade_policy"]["should_force_hold"] is True
    assert result["state"]["degrade_policy"]["budget_recovery_guard"]["active"] is True
    assert broker.executed is False


def test_budget_recovery_guard_auto_releases(monkeypatch):
    _patch_ledger(monkeypatch)
    monkeypatch.setenv("TRADE_DEGRADE_ENABLED_RULES", "llm_daily_budget_exceeded")
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "1.0")
    monkeypatch.setenv("TRADE_DEGRADE_LLM_BUDGET_ACTION", "force_hold")
    monkeypatch.setenv("TRADE_BUDGET_RECOVERY_ENABLED", "true")
    monkeypatch.setenv("TRADE_BUDGET_RECOVERY_RATIO", "0.8")
    monkeypatch.setenv("TRADE_BUDGET_RECOVERY_COOLDOWN_S", "0")
    broker = FakeBroker()
    service = TradingService(trading_channel="simulation", vm=BudgetForceHoldVM(), broker=broker)
    service._china_data_disabled = True

    import asyncio

    first = asyncio.run(service.execute("000001"))
    assert first["decision"] == "HOLD"
    assert first["state"]["degrade_policy"]["budget_recovery_guard"]["active"] is True

    service.vm = BudgetRecoverVM()
    second = asyncio.run(service.execute("000001"))
    assert second["decision"] == "BUY"
    assert second["order"] is not None
    guard = second["state"]["degrade_policy"]["budget_recovery_guard"]
    assert guard["active"] is False
    metrics = guard["metrics"]
    assert metrics["activation_count"] == 1
    assert metrics["release_count"] >= 1
    assert metrics["auto_recovery_success_count"] == 1
    assert metrics["recovery_success_rate"] == pytest.approx(1.0)
    assert metrics["avg_recovery_duration_s"] >= 0.0

    runtime = service.get_runtime_state()
    assert "budget_recovery_metrics" in runtime
    assert runtime["budget_recovery_metrics"]["activation_count"] == 1
    assert "core_governance" in runtime


def test_day_roll_resets_state_and_calls_broker_new_day(monkeypatch):
    _patch_ledger(monkeypatch)
    broker = FakeBroker()
    service = TradingService(trading_channel="simulation", vm=HoldVM(), broker=broker)
    service._china_data_disabled = True
    service.simulation_days = 3

    async def _mock_reconcile(initial_cash=None):
        return {"status": "matched", "issues_count": 0}

    service.reconcile = _mock_reconcile  # type: ignore[assignment]

    import asyncio

    result = asyncio.run(service.day_roll(reason="unit_test"))
    assert result["simulation_days"] == 4
    assert result["broker_new_day"] is True
    assert broker.new_day_called is True


def test_day_roll_skips_on_non_trading_day(monkeypatch):
    _patch_ledger(monkeypatch)
    broker = FakeBroker()
    service = TradingService(trading_channel="simulation", vm=HoldVM(), broker=broker)
    service._china_data_disabled = True
    service.calendar.is_trading_day = lambda target=None: False  # type: ignore[assignment]
    service.calendar.next_trading_day = lambda from_date=None: from_date  # type: ignore[assignment]

    import asyncio

    result = asyncio.run(service.day_roll(reason="weekend", force=False))
    assert result["skipped"] is True
    assert result["code"] == "NON_TRADING_DAY"


def test_execute_blocked_by_reconciliation():
    broker = FakeBroker()
    service = TradingService(trading_channel="simulation", vm=BuyVM(), broker=broker)
    service._reconciliation_blocked = True
    service._reconciliation_block_reason = {"code": "RECON_BLOCK"}

    import asyncio

    with pytest.raises(TradingServiceError) as exc_info:
        asyncio.run(service.execute("000001"))
    assert exc_info.value.code == "RECON_BLOCKED"


def test_reconciliation_auto_unlock_after_consecutive_ok(monkeypatch):
    _patch_ledger(monkeypatch)
    broker = FakeBroker()
    service = TradingService(trading_channel="simulation", vm=HoldVM(), broker=broker)
    service._auto_unblock_enabled = True
    service._auto_unblock_required_ok_streak = 2

    service._apply_reconciliation_guard(
        {"code": "RECON_BLOCK", "action": "block", "alert_level": "critical", "issues_count": 2}
    )
    assert service._reconciliation_blocked is True

    service._apply_reconciliation_guard({"code": "RECON_OK", "action": "record"})
    assert service._reconciliation_blocked is True
    assert service._reconciliation_ok_streak == 1

    service._apply_reconciliation_guard({"code": "RECON_OK", "action": "record"})
    assert service._reconciliation_blocked is False
    assert service._reconciliation_ok_streak == 2


def test_reconciliation_block_not_unlocked_by_warn(monkeypatch):
    _patch_ledger(monkeypatch)
    broker = FakeBroker()
    service = TradingService(trading_channel="simulation", vm=HoldVM(), broker=broker)
    service._auto_unblock_enabled = True
    service._auto_unblock_required_ok_streak = 2

    service._apply_reconciliation_guard(
        {"code": "RECON_BLOCK", "action": "block", "alert_level": "critical", "issues_count": 1}
    )
    service._apply_reconciliation_guard({"code": "RECON_WARN", "action": "record"})

    assert service._reconciliation_blocked is True
    assert service._reconciliation_ok_streak == 0


def test_reconciliation_manual_unlock(monkeypatch):
    _patch_ledger(monkeypatch)
    broker = FakeBroker()
    service = TradingService(trading_channel="simulation", vm=HoldVM(), broker=broker)
    service._reconciliation_blocked = True
    service._reconciliation_block_reason = {"code": "RECON_BLOCK", "issues_count": 3}

    result = service.unlock_reconciliation_block(reason="operator_override", operator="unit_test")
    assert result["was_blocked"] is True
    assert service._reconciliation_blocked is False
    assert service._reconciliation_block_reason == {}


def test_get_trade_snapshot(monkeypatch):
    _patch_ledger(monkeypatch)
    broker = FakeBroker()
    service = TradingService(trading_channel="simulation", vm=HoldVM(), broker=broker)
    service._china_data_disabled = True

    import asyncio

    snapshot = asyncio.run(service.get_trade_snapshot(include_channel_raw=False))
    assert snapshot["channel"] == "simulation"
    assert snapshot["broker_connected"] is True
    assert "balance" in snapshot
    assert "positions" in snapshot
    assert "orders" in snapshot
    assert "reconciliation_guard" in snapshot
    assert snapshot["total_value"] == 1_000_000.0
    assert snapshot["daily_pnl"] == 0.0
    assert snapshot["holding_value"] == 0.0
    assert snapshot["cash"] == 1_000_000.0
    assert isinstance(snapshot["strategies"], list)


def test_get_trade_snapshot_includes_channel_info_and_raw(monkeypatch):
    _patch_ledger(monkeypatch)
    broker = FakeBroker()
    service = TradingService(trading_channel="simulation", vm=HoldVM(), broker=broker)
    service._china_data_disabled = True

    import asyncio

    snapshot = asyncio.run(service.get_trade_snapshot(include_channel_raw=True))
    assert snapshot["channel_info"]["channel"] == "simulation"
    assert snapshot["channel_info"]["status"] == "active"
    assert snapshot["channel_raw"]["status"] == "success"
    assert snapshot["channel_raw"]["meta"]["channel"] == "simulation"


def test_execute_persists_evidence_with_trace_and_policy(monkeypatch):
    from src.core import trading_service as ts_module

    captured: dict[str, object] = {}

    monkeypatch.setattr(ts_module.TradingLedger, "record_trade", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(ts_module.TradingLedger, "record_analysis", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(ts_module.TradingLedger, "record_entry", staticmethod(lambda *args, **kwargs: None))

    def _capture(payload):
        captured["payload"] = payload
        return "evidence"

    monkeypatch.setattr(ts_module.TradingLedger, "record_decision_evidence", staticmethod(_capture))

    broker = FakeBroker()
    service = TradingService(trading_channel="simulation", vm=HoldVM(), broker=broker)
    service._china_data_disabled = True

    import asyncio

    _ = asyncio.run(service.execute("000001"))
    payload = captured.get("payload", {})
    assert isinstance(payload, dict)
    assert payload["evidence_version"]
    assert payload["trace"]["trace_id"]
    assert payload["degrade_policy"]["policy_version"]
    assert "dataflow_quality" in payload["context_digest"]
