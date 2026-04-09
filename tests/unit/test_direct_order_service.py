from __future__ import annotations

import asyncio
import uuid

import pytest

from src.core.errors import TradingServiceError
from src.core.trading_service import TradingService
from src.execution.base import AccountBalance, BaseBroker, OrderResult, OrderSide, OrderStatus


class _DirectBroker(BaseBroker):
    channel_name = "simulation"

    def __init__(self):
        self._connected = False
        self.buy_calls = 0
        self.sell_calls = 0

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> bool:
        self._connected = True
        return True

    async def disconnect(self):
        self._connected = False

    async def buy(self, ticker: str, price: float, quantity: int, **kwargs) -> OrderResult:
        self.buy_calls += 1
        return OrderResult(
            order_id="dir-order-1",
            status=OrderStatus.SUBMITTED,
            ticker=ticker,
            side=OrderSide.BUY,
            price=price,
            quantity=quantity,
            channel=self.channel_name,
            message="broker_order_id=BRK-001;remark=test",
        )

    async def sell(self, ticker: str, price: float, quantity: int, **kwargs) -> OrderResult:
        self.sell_calls += 1
        return OrderResult(
            order_id="dir-order-2",
            status=OrderStatus.SUBMITTED,
            ticker=ticker,
            side=OrderSide.SELL,
            price=price,
            quantity=quantity,
            channel=self.channel_name,
            message="broker_order_id=BRK-002;remark=test",
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


class _HoldVM:
    async def run(self, ticker: str, initial_context=None):
        _ = ticker
        _ = initial_context
        return {
            "session_id": "fallback",
            "ticker": "",
            "decision": "HOLD",
            "confidence": 0.0,
            "analysis_reports": {},
            "context": {},
            "trading_decision": {"action": "HOLD", "percentage": 0, "reason": "hold", "confidence": 0},
        }


def _patch_direct_ledger(monkeypatch):
    from src.core import trading_service as ts_module

    store: dict[str, dict] = {}
    trades: dict[str, dict] = {}

    def _create(**kwargs):
        record = {
            "id": f"req-{kwargs['idempotency_key']}",
            "created_at": 1.0,
            "updated_at": 1.0,
            "request_id": kwargs["request_id"],
            "idempotency_key": kwargs["idempotency_key"],
            "client_order_id": kwargs.get("client_order_id", ""),
            "local_order_id": "",
            "broker_order_id": "",
            "channel": kwargs["channel"],
            "ticker": kwargs["ticker"],
            "side": kwargs["side"],
            "quantity": kwargs["quantity"],
            "price": kwargs["price"],
            "order_type": kwargs.get("order_type", "limit"),
            "status": "received",
            "error_code": "",
            "error_message": "",
            "response_payload": kwargs.get("response_payload", {}),
        }
        store[kwargs["idempotency_key"]] = record
        return {"created": True, "record": dict(record)}

    def _get(key: str):
        item = store.get(key)
        return dict(item) if item else None

    def _finalize(**kwargs):
        item = store.get(kwargs["idempotency_key"], {})
        item["status"] = kwargs.get("status", item.get("status", ""))
        item["local_order_id"] = kwargs.get("local_order_id", item.get("local_order_id", "")) or item.get(
            "local_order_id", ""
        )
        item["broker_order_id"] = kwargs.get("broker_order_id", item.get("broker_order_id", "")) or item.get(
            "broker_order_id", ""
        )
        item["error_code"] = kwargs.get("error_code", "")
        item["error_message"] = kwargs.get("error_message", "")
        item["response_payload"] = kwargs.get("response_payload", {})
        store[kwargs["idempotency_key"]] = item
        return dict(item)

    def _record_trade(trade):
        payload = {
            "id": trade.id,
            "status": trade.status,
            "filled_price": trade.filled_price,
            "filled_quantity": trade.filled_quantity,
            "metadata": trade.metadata,
        }
        trades[trade.id] = payload
        return True

    def _get_trace(**kwargs):
        if kwargs.get("idempotency_key"):
            item = store.get(kwargs["idempotency_key"])
            return dict(item) if item else None
        if kwargs.get("local_order_id"):
            for item in store.values():
                if item.get("local_order_id") == kwargs["local_order_id"]:
                    return dict(item)
        if kwargs.get("trace_id"):
            for item in store.values():
                payload = item.get("response_payload", {}) if isinstance(item.get("response_payload", {}), dict) else {}
                payload_trace = payload.get("trace", {}) if isinstance(payload.get("trace", {}), dict) else {}
                trace_id = str(payload.get("trace_id", "") or payload_trace.get("trace_id", ""))
                if trace_id == kwargs["trace_id"]:
                    return dict(item)
        return None

    monkeypatch.setattr(ts_module.TradingLedger, "create_direct_order_request", staticmethod(_create))
    monkeypatch.setattr(ts_module.TradingLedger, "get_direct_order_request", staticmethod(_get))
    monkeypatch.setattr(ts_module.TradingLedger, "finalize_direct_order_request", staticmethod(_finalize))
    monkeypatch.setattr(ts_module.TradingLedger, "record_trade", staticmethod(_record_trade))
    monkeypatch.setattr(ts_module.TradingLedger, "record_decision_evidence", staticmethod(lambda *args, **kwargs: "ev"))
    monkeypatch.setattr(ts_module.TradingLedger, "record_entry", staticmethod(lambda *args, **kwargs: None))
    monkeypatch.setattr(ts_module.TradingLedger, "get_direct_order_trace", staticmethod(_get_trace))
    monkeypatch.setattr(ts_module.TradingLedger, "get_trade", staticmethod(lambda trade_id: trades.get(trade_id)))


def test_place_direct_order_idempotent_replay(monkeypatch):
    _patch_direct_ledger(monkeypatch)
    broker = _DirectBroker()
    service = TradingService(trading_channel="simulation", vm=_HoldVM(), broker=broker)
    service._china_data_disabled = True

    first = asyncio.run(
        service.place_direct_order(
            ticker="000001",
            side="BUY",
            quantity=100,
            price=10.0,
            order_type="limit",
            idempotency_key="idem-001",
            client_order_id="co-001",
            request_id="req-001",
            channel="simulation",
            memo="unit",
        )
    )
    second = asyncio.run(
        service.place_direct_order(
            ticker="000001",
            side="BUY",
            quantity=100,
            price=10.0,
            order_type="limit",
            idempotency_key="idem-001",
            client_order_id="co-001",
            request_id="req-001",
            channel="simulation",
            memo="unit",
        )
    )

    assert first["idempotent_replay"] is False
    assert second["idempotent_replay"] is True
    assert first["trace"]["local_order_id"] == "dir-order-1"
    assert first["trace"]["broker_order_id"] == "BRK-001"
    assert broker.buy_calls == 1


def test_get_direct_order_trace_contains_trade_status(monkeypatch):
    _patch_direct_ledger(monkeypatch)
    broker = _DirectBroker()
    service = TradingService(trading_channel="simulation", vm=_HoldVM(), broker=broker)
    service._china_data_disabled = True

    asyncio.run(
        service.place_direct_order(
            ticker="000001",
            side="BUY",
            quantity=100,
            price=10.0,
            order_type="limit",
            idempotency_key="idem-002",
            client_order_id="co-002",
            request_id="req-002",
            channel="simulation",
            memo="unit",
        )
    )
    trace = service.get_direct_order_trace(idempotency_key="idem-002")
    assert trace is not None
    assert trace["local_order_id"] == "dir-order-1"
    assert trace["broker_order_id"] == "BRK-001"
    assert trace["trade_status"] == "submitted"


def test_place_direct_order_requires_manual_confirm(monkeypatch):
    monkeypatch.setenv("DIRECT_ORDER_REQUIRE_MANUAL_CONFIRM", "true")
    monkeypatch.setenv("DIRECT_ORDER_CONFIRM_TOKEN", "unit-token")
    _patch_direct_ledger(monkeypatch)

    service = TradingService(trading_channel="simulation", vm=_HoldVM(), broker=_DirectBroker())
    service._china_data_disabled = True

    with pytest.raises(TradingServiceError) as exc:
        asyncio.run(
            service.place_direct_order(
                ticker="000001",
                side="BUY",
                quantity=100,
                price=10.0,
                order_type="limit",
                idempotency_key=f"idem-{uuid.uuid4().hex[:8]}",
                request_id="req-manual-missing",
                channel="simulation",
            )
        )
    assert exc.value.code == "DIRECT_ORDER_MANUAL_CONFIRM_REQUIRED"


def test_place_direct_order_rejects_not_whitelisted_ticker(monkeypatch):
    monkeypatch.setenv("DIRECT_ORDER_WHITELIST_ENABLED", "true")
    monkeypatch.setenv("DIRECT_ORDER_TICKER_WHITELIST", "600000,600519")
    _patch_direct_ledger(monkeypatch)

    service = TradingService(trading_channel="simulation", vm=_HoldVM(), broker=_DirectBroker())
    service._china_data_disabled = True

    with pytest.raises(TradingServiceError) as exc:
        asyncio.run(
            service.place_direct_order(
                ticker="000001",
                side="BUY",
                quantity=100,
                price=10.0,
                order_type="limit",
                idempotency_key=f"idem-{uuid.uuid4().hex[:8]}",
                request_id="req-whitelist",
                channel="simulation",
                manual_confirm=True,
            )
        )
    assert exc.value.code == "DIRECT_ORDER_TICKER_NOT_ALLOWED"


def test_place_direct_order_rate_limited(monkeypatch):
    monkeypatch.setenv("DIRECT_ORDER_MAX_ORDERS_PER_MINUTE", "1")
    _patch_direct_ledger(monkeypatch)

    broker = _DirectBroker()
    service = TradingService(trading_channel="simulation", vm=_HoldVM(), broker=broker)
    service._china_data_disabled = True

    asyncio.run(
        service.place_direct_order(
            ticker="000001",
            side="BUY",
            quantity=100,
            price=10.0,
            order_type="limit",
            idempotency_key=f"idem-{uuid.uuid4().hex[:8]}",
            request_id="req-rate-1",
            channel="simulation",
            manual_confirm=True,
        )
    )
    with pytest.raises(TradingServiceError) as exc:
        asyncio.run(
            service.place_direct_order(
                ticker="000001",
                side="BUY",
                quantity=100,
                price=10.0,
                order_type="limit",
                idempotency_key=f"idem-{uuid.uuid4().hex[:8]}",
                request_id="req-rate-2",
                channel="simulation",
                manual_confirm=True,
            )
        )
    assert exc.value.code == "DIRECT_ORDER_RATE_LIMITED"


def test_place_direct_order_window_closed(monkeypatch):
    monkeypatch.setenv("DIRECT_ORDER_ENFORCE_TRADING_WINDOW", "true")
    monkeypatch.setenv("DIRECT_ORDER_ALLOW_NON_TRADING_DAY", "true")
    monkeypatch.setenv("DIRECT_ORDER_TRADING_SESSIONS", "00:00-00:01")
    _patch_direct_ledger(monkeypatch)

    service = TradingService(trading_channel="simulation", vm=_HoldVM(), broker=_DirectBroker())
    service._china_data_disabled = True

    with pytest.raises(TradingServiceError) as exc:
        asyncio.run(
            service.place_direct_order(
                ticker="000001",
                side="BUY",
                quantity=100,
                price=10.0,
                order_type="limit",
                idempotency_key=f"idem-{uuid.uuid4().hex[:8]}",
                request_id="req-window",
                channel="simulation",
                manual_confirm=True,
            )
        )
    assert exc.value.code == "DIRECT_ORDER_WINDOW_CLOSED"


def test_place_direct_order_trace_id_propagates(monkeypatch):
    _patch_direct_ledger(monkeypatch)
    broker = _DirectBroker()
    service = TradingService(trading_channel="simulation", vm=_HoldVM(), broker=broker)
    service._china_data_disabled = True

    payload = asyncio.run(
        service.place_direct_order(
            ticker="000001",
            side="BUY",
            quantity=100,
            price=10.0,
            order_type="limit",
            idempotency_key=f"idem-{uuid.uuid4().hex[:8]}",
            request_id="req-trace-id",
            trace_id="trace-unit-001",
            channel="simulation",
            manual_confirm=True,
        )
    )
    assert payload["trace_id"] == "trace-unit-001"
    assert payload["trace"]["trace_id"] == "trace-unit-001"
    traced = service.get_direct_order_trace(trace_id="trace-unit-001")
    assert traced is not None
    assert traced["trace_id"] == "trace-unit-001"
