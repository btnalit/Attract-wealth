"""
交易编排服务。

将数据构建、决策图、风控、执行通道、订单同步、对账、审计写入串成统一调用链。
"""
from __future__ import annotations

import asyncio
import copy
import logging
import os
import time
import uuid
from dataclasses import asdict
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from src.core.budget_guard import BudgetRecoveryGuard
from src.core.reconciliation_guard import ReconciliationGuard
from src.core.direct_order_guard import DirectOrderGuard
from src.core.degrade_policy import build_default_degrade_policy
from src.core.errors import TradingServiceError
from src.core.trading_calendar import CNTradingCalendar
from src.core.trading_ledger import AnalysisReport, LedgerEntry, TradeRecord, TradingLedger
from src.execution.base import AccountBalance, OrderRequest, OrderSide, OrderStatus, Position
from src.execution.broker_factory import create_broker
from src.execution.order_manager import OrderManager
from src.execution.reconciliation import ReconciliationEngine
from src.execution.risk_gate import RiskGate
from src.llm.openai_compat import apply_llm_runtime_config, get_llm_effective_config, get_llm_runtime_metrics

logger = logging.getLogger(__name__)
ACTIVE_ORDER_STATUSES = {OrderStatus.PENDING, OrderStatus.SUBMITTED, OrderStatus.PARTIAL}
EVIDENCE_REQUIRED_PATHS: tuple[str, ...] = (
    "evidence_version",
    "phase",
    "session_id",
    "request_id",
    "ticker",
    "channel",
    "trace.trace_id",
    "trace.request_id",
    "risk_check",
    "analysis_reports",
    "debate_results",
    "degrade_policy",
    "budget_recovery_guard",
    "reconciliation_guard",
    "context_digest",
    "llm_runtime",
)

if TYPE_CHECKING:
    from src.core.trading_vm import TradingVM


class TradingService:
    """统一交易业务入口。"""

    def __init__(
        self,
        trading_channel: Optional[str] = None,
        vm: Optional[Any] = None,
        risk_gate: Optional[RiskGate] = None,
        broker: Optional[Any] = None,
    ):
        self.channel = (trading_channel or os.getenv("TRADING_CHANNEL", "ths_auto")).strip().lower()
        self.vm = vm or self._create_vm_with_fallback()
        self.risk_gate = risk_gate or RiskGate()
        self.broker = broker or create_broker(self.channel)
        self.simulation_days = int(os.getenv("SIMULATION_DAYS", "0"))
        self.calendar = CNTradingCalendar()
        self.degrade_policy = build_default_degrade_policy()
        
        # 架构审计优化：剥离保护器逻辑
        self.budget_guard = BudgetRecoveryGuard()
        self.recon_guard = ReconciliationGuard()
        self.direct_guard = DirectOrderGuard(self.calendar)

        self.order_manager = OrderManager(self.broker)
        self.reconciliation_engine = ReconciliationEngine(self.broker)
        self._order_sync_enabled = os.getenv("ORDER_SYNC_ENABLED", "true").lower() == "true"
        self._order_sync_interval = float(os.getenv("ORDER_SYNC_INTERVAL", "30"))
        self._order_sync_task: Optional[asyncio.Task] = None

        self._china_data = None
        self._china_data_disabled = False
        self._initialized = False

    async def initialize(self):
        """初始化并连接执行通道，失败时自动降级到 simulation。"""
        if self._initialized:
            return
        await self._ensure_broker_connected()
        self._start_order_sync_if_needed()
        self._initialized = True

    async def shutdown(self):
        try:
            await self._stop_order_sync_if_needed()
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        try:
            if hasattr(self.broker, "disconnect"):
                await self.broker.disconnect()
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        self._initialized = False

    def get_llm_runtime_config(self) -> dict[str, Any]:
        return get_llm_effective_config()

    def update_llm_runtime_config(self, config: dict[str, Any], *, operator: str = "api") -> dict[str, Any]:
        applied = apply_llm_runtime_config(config, persist_env=True)
        # Rebuild VM so newly created agents pick up the updated LLM config.
        self.vm = self._create_vm_with_fallback()
        TradingLedger.record_entry(
            LedgerEntry(
                category="SYSTEM",
                action="LLM_CONFIG_UPDATED",
                detail="llm runtime config updated from api",
                metadata={
                    "operator": operator,
                    "provider_name": applied.get("provider_name", ""),
                    "base_url": applied.get("base_url", ""),
                    "model": applied.get("model", ""),
                    "quick_model": applied.get("quick_model", ""),
                    "deep_model": applied.get("deep_model", ""),
                    "timeout_s": applied.get("timeout_s", 0),
                    "max_tokens": applied.get("max_tokens", 0),
                    "temperature": applied.get("temperature", 0),
                },
            )
        )
        return applied

    async def analyze(self, ticker: str) -> dict[str, Any]:
        await self._ensure_broker_connected()
        context = await self._build_context(ticker)
        state = await self.vm.run(ticker=ticker, initial_context=context)
        self._ensure_state_trace(state, phase="analyze")
        self._annotate_policy_snapshot(state)
        self._persist_analysis_reports(ticker=ticker, state=state)
        self._persist_decision_evidence(
            ticker=ticker,
            state=state,
            phase="analyze",
            risk_check={},
            order=None,
        )
        return {"ticker": ticker, "channel": self.channel, "state": state}

    async def execute(self, ticker: str) -> dict[str, Any]:
        if self.recon_guard.blocked:
            raise TradingServiceError(
                code="RECON_BLOCKED",
                message="对账结果触发阻断，已暂停下单。",
                details=self._reconciliation_block_reason,
                http_status=409,
            )

        analysis = await self.analyze(ticker)
        state = analysis["state"]
        self._ensure_state_trace(state, phase="execute")
        self._apply_failure_degrade(state)
        request = self._build_order_request(state)
        if not request:
            result = {
                "ticker": ticker,
                "channel": self.channel,
                "decision": state.get("decision", "HOLD"),
                "risk_check": {"passed": True, "reason": "No executable order"},
                "order": None,
                "state": state,
            }
            self._persist_decision_evidence(
                ticker=ticker,
                state=state,
                phase="execute",
                risk_check=result.get("risk_check", {}),
                order=None,
            )
            return result

        account = await self._safe_get_balance()
        positions = await self._safe_get_positions()
        current_positions = {p.ticker: p.market_value for p in positions}
        daily_pnl = account.daily_pnl if account else 0.0
        total_assets = account.total_assets if account and account.total_assets > 0 else 0.0

        passed, violations = self.risk_gate.check_order(
            request=request,
            total_assets=total_assets,
            current_positions=current_positions,
            daily_pnl=daily_pnl,
            is_live=self.channel != "simulation",
            simulation_days=self.simulation_days,
        )
        if not passed:
            TradingLedger.record_entry(
                LedgerEntry(
                    category="RISK",
                    level="WARNING",
                    action="CHECK_REJECT",
                    detail=f"risk rejected order {request.ticker} {request.side.value} {request.quantity}",
                    status="rejected",
                    metadata={
                        "ticker": request.ticker,
                        "side": request.side.value,
                        "quantity": request.quantity,
                        "price": request.price,
                        "violations": [asdict(v) for v in violations],
                    },
                )
            )
            result = {
                "ticker": ticker,
                "channel": self.channel,
                "decision": state.get("decision", "HOLD"),
                "risk_check": {"passed": False, "violations": [asdict(v) for v in violations]},
                "order": None,
                "state": state,
            }
            self._persist_decision_evidence(
                ticker=ticker,
                state=state,
                phase="execute",
                risk_check=result.get("risk_check", {}),
                order=None,
            )
            return result

        order = await self.broker.execute_order(request)
        self._persist_trade(state=state, order=order)
        self.order_manager.add_active_order(order)
        result = {
            "ticker": ticker,
            "channel": self.channel,
            "decision": state.get("decision", "HOLD"),
            "risk_check": {"passed": True, "reason": "All checks cleared"},
            "order": asdict(order),
            "state": state,
        }
        self._persist_decision_evidence(
            ticker=ticker,
            state=state,
            phase="execute",
            risk_check=result.get("risk_check", {}),
            order=result.get("order"),
        )
        return result

    async def place_direct_order(
        self,
        *,
        ticker: str,
        side: str,
        quantity: int,
        price: float,
        order_type: str,
        idempotency_key: str,
        client_order_id: str = "",
        request_id: str = "",
        channel: str = "",
        memo: str = "",
        manual_confirm: bool = False,
        manual_confirm_token: str = "",
        trace_id: str = "",
    ) -> dict[str, Any]:
        if self.recon_guard.blocked:
            raise TradingServiceError(
                code="RECON_BLOCKED",
                message="reconciliation guard is blocking order placement",
                details=self._reconciliation_block_reason,
                http_status=409,
            )

        norm_ticker = str(ticker or "").strip()
        norm_side = str(side or "").strip().upper()
        norm_order_type = str(order_type or "limit").strip().lower()
        norm_channel = (str(channel or "").strip().lower() or self.channel)
        norm_idempotency = str(idempotency_key or "").strip()
        norm_client_order_id = str(client_order_id or "").strip()
        norm_request_id = str(request_id or "").strip() or f"req-{uuid.uuid4().hex[:12]}"
        norm_memo = str(memo or "").strip()
        norm_trace_id = str(trace_id or "").strip() or norm_request_id

        if norm_channel != self.channel:
            raise TradingServiceError(
                code="CHANNEL_MISMATCH",
                message="request channel does not match active trading channel",
                details={"requested_channel": norm_channel, "active_channel": self.channel},
                http_status=409,
            )
        if not norm_ticker:
            raise TradingServiceError(code="INVALID_ORDER_REQUEST", message="ticker is required", http_status=400)
        if norm_side not in {"BUY", "SELL"}:
            raise TradingServiceError(code="INVALID_ORDER_REQUEST", message="side must be BUY or SELL", http_status=400)
        if int(quantity or 0) <= 0:
            raise TradingServiceError(code="INVALID_ORDER_REQUEST", message="quantity must be > 0", http_status=400)
        if float(price or 0) <= 0:
            raise TradingServiceError(code="INVALID_ORDER_REQUEST", message="price must be > 0", http_status=400)
        if norm_order_type not in {"limit", "market"}:
            raise TradingServiceError(
                code="INVALID_ORDER_REQUEST",
                message="order_type must be limit or market",
                http_status=400,
            )
        if not norm_idempotency:
            raise TradingServiceError(code="INVALID_ORDER_REQUEST", message="idempotency_key is required", http_status=400)

        request_signature = {
            "channel": norm_channel,
            "ticker": norm_ticker,
            "side": norm_side,
            "quantity": int(quantity),
            "price": float(price),
            "order_type": norm_order_type,
            "client_order_id": norm_client_order_id,
        }
        existing = TradingLedger.get_direct_order_request(norm_idempotency)
        if existing:
            if not self._direct_order_signature_match(existing, request_signature):
                raise TradingServiceError(
                    code="IDEMPOTENCY_CONFLICT",
                    message="idempotency key conflicts with existing payload",
                    details={"existing": existing, "incoming": request_signature},
                    http_status=409,
                )
            replay_payload = copy.deepcopy(existing.get("response_payload", {}) or {})
            replay_payload["idempotent_replay"] = True
            replay_payload["request_id"] = existing.get("request_id") or norm_request_id
            replay_trace = self._build_direct_trace(existing)
            replay_trace["trace_id"] = str(
                replay_payload.get("trace_id", "")
                or (replay_payload.get("trace", {}) or {}).get("trace_id", "")
                or norm_trace_id
            )
            replay_payload["trace"] = replay_trace
            replay_payload["trace_id"] = replay_trace["trace_id"]
            TradingLedger.record_entry(
                LedgerEntry(
                    category="TRADE",
                    action="DIRECT_ORDER_REPLAY",
                    detail=f"direct order idempotent replay {norm_ticker}",
                    metadata={
                        "trace_id": replay_trace["trace_id"],
                        "request_id": replay_payload["request_id"],
                        "idempotency_key": norm_idempotency,
                        "channel": norm_channel,
                    },
                )
            )
            return replay_payload

        order_notional = self._enforce_direct_order_safety(
            ticker=norm_ticker,
            side=norm_side,
            quantity=int(quantity),
            price=float(price),
            manual_confirm=bool(manual_confirm),
            manual_confirm_token=manual_confirm_token,
        )

        trace = {
            "trace_id": norm_trace_id,
            "request_id": norm_request_id,
            "idempotency_key": norm_idempotency,
            "channel": norm_channel,
            "client_order_id": norm_client_order_id,
            "local_order_id": "",
            "broker_order_id": "",
            "status": "received",
            "steps": {
                "request": {"status": "ok", "at": time.time()},
                "safety": {"status": "passed", "at": time.time()},
            },
        }

        TradingLedger.create_direct_order_request(
            request_id=norm_request_id,
            idempotency_key=norm_idempotency,
            client_order_id=norm_client_order_id,
            channel=norm_channel,
            ticker=norm_ticker,
            side=norm_side,
            quantity=int(quantity),
            price=float(price),
            order_type=norm_order_type,
            response_payload={
                "request_id": norm_request_id,
                "trace_id": norm_trace_id,
                "status": "received",
                "trace": trace,
            },
        )
        TradingLedger.record_entry(
            LedgerEntry(
                category="TRADE",
                action="DIRECT_ORDER_REQUEST",
                detail=f"direct order request received {norm_ticker}",
                metadata={
                    "trace_id": norm_trace_id,
                    "request_id": norm_request_id,
                    "idempotency_key": norm_idempotency,
                    "channel": norm_channel,
                    "ticker": norm_ticker,
                    "side": norm_side,
                    "quantity": int(quantity),
                    "price": float(price),
                },
            )
        )

        await self._ensure_broker_connected()
        order_request = OrderRequest(
            ticker=norm_ticker,
            side=OrderSide.BUY if norm_side == "BUY" else OrderSide.SELL,
            price=round(float(price), 3),
            quantity=int(quantity),
            market="CN",
            order_type=norm_order_type,
            memo=norm_memo,
            agent_id="external_api",
        )

        account = await self._safe_get_balance()
        positions = await self._safe_get_positions()
        current_positions = {p.ticker: p.market_value for p in positions}
        daily_pnl = account.daily_pnl if account else 0.0
        total_assets = account.total_assets if account and account.total_assets > 0 else 0.0
        passed, violations = self.risk_gate.check_order(
            request=order_request,
            total_assets=total_assets,
            current_positions=current_positions,
            daily_pnl=daily_pnl,
            is_live=self.channel != "simulation",
            simulation_days=self.simulation_days,
        )

        if not passed:
            risk_check = {"passed": False, "violations": [asdict(v) for v in violations]}
            trace["status"] = "risk_rejected"
            trace["steps"]["risk"] = {"status": "rejected", "at": time.time(), "violations": risk_check["violations"]}
            trace["steps"]["reconciliation"] = {
                "status": "blocked" if self.recon_guard.blocked else "ok",
                "at": time.time(),
                "guard": self.get_reconciliation_guard_state(),
            }
            payload = {
                "request_id": norm_request_id,
                "idempotency_key": norm_idempotency,
                "channel": norm_channel,
                "trace_id": norm_trace_id,
                "risk_check": risk_check,
                "order": None,
                "trace": trace,
                "idempotent_replay": False,
            }
            evidence_id = self._persist_direct_order_evidence(
                request_id=norm_request_id,
                idempotency_key=norm_idempotency,
                client_order_id=norm_client_order_id,
                ticker=norm_ticker,
                side=norm_side,
                channel=norm_channel,
                risk_check=risk_check,
                order=None,
                trace=payload.get("trace", {}),
                status="risk_rejected",
                request_payload=request_signature,
                trace_id=norm_trace_id,
            )
            trace["steps"]["audit"] = {"status": "persisted", "at": time.time(), "evidence_id": evidence_id}
            payload["evidence_id"] = evidence_id
            TradingLedger.finalize_direct_order_request(
                idempotency_key=norm_idempotency,
                status="risk_rejected",
                error_code="RISK_REJECTED",
                error_message="risk gate rejected direct order",
                response_payload=payload,
            )
            TradingLedger.record_entry(
                LedgerEntry(
                    category="RISK",
                    level="WARNING",
                    action="DIRECT_ORDER_RISK_REJECTED",
                    detail=f"direct order risk rejected {norm_ticker}",
                    status="rejected",
                    metadata={
                        "trace_id": norm_trace_id,
                        "request_id": norm_request_id,
                        "idempotency_key": norm_idempotency,
                        "violations": risk_check["violations"],
                    },
                )
            )
            return payload

        self.direct_guard.daily_notional = round(self.direct_guard.daily_notional + order_notional, 6)
        order = await self.broker.execute_order(order_request)
        local_order_id = str(getattr(order, "order_id", "") or "")
        broker_order_id = self._extract_broker_order_id(order.message)
        order_status = order.status.value if hasattr(order.status, "value") else str(order.status)
        trace["local_order_id"] = local_order_id
        trace["broker_order_id"] = broker_order_id
        trace["status"] = order_status
        trace["steps"]["risk"] = {"status": "passed", "at": time.time()}
        trace["steps"]["execute"] = {
            "status": order_status,
            "at": time.time(),
            "local_order_id": local_order_id,
            "broker_order_id": broker_order_id,
        }
        trace["steps"]["reconciliation"] = {
            "status": "blocked" if self.recon_guard.blocked else "ok",
            "at": time.time(),
            "guard": self.get_reconciliation_guard_state(),
        }
        payload = {
            "request_id": norm_request_id,
            "idempotency_key": norm_idempotency,
            "channel": norm_channel,
            "trace_id": norm_trace_id,
            "risk_check": {"passed": True, "reason": "All checks cleared"},
            "order": asdict(order),
            "trace": trace,
            "idempotent_replay": False,
        }

        self._persist_direct_trade(
            order=order,
            trace=trace,
            request_payload=request_signature,
            idempotency_key=norm_idempotency,
            request_id=norm_request_id,
        )
        if order.status in ACTIVE_ORDER_STATUSES:
            self.order_manager.add_active_order(order)

        error_code = ""
        if order.status == OrderStatus.REJECTED:
            error_code = "ORDER_REJECTED"
        elif order.status == OrderStatus.FAILED:
            error_code = "ORDER_FAILED"

        evidence_id = self._persist_direct_order_evidence(
            request_id=norm_request_id,
            idempotency_key=norm_idempotency,
            client_order_id=norm_client_order_id,
            ticker=norm_ticker,
            side=norm_side,
            channel=norm_channel,
            risk_check=payload.get("risk_check", {}),
            order=payload.get("order", {}),
            trace=trace,
            status=order_status,
            request_payload=request_signature,
            trace_id=norm_trace_id,
        )
        trace["steps"]["audit"] = {"status": "persisted", "at": time.time(), "evidence_id": evidence_id}
        payload["evidence_id"] = evidence_id
        TradingLedger.finalize_direct_order_request(
            idempotency_key=norm_idempotency,
            status=order_status,
            local_order_id=local_order_id,
            broker_order_id=broker_order_id,
            error_code=error_code,
            error_message=str(order.message or ""),
            response_payload=payload,
        )
        TradingLedger.record_entry(
            LedgerEntry(
                category="TRADE",
                level="INFO" if error_code == "" else "WARNING",
                action="DIRECT_ORDER_EXECUTED",
                detail=f"direct order executed {norm_ticker} status={order_status}",
                status=order_status,
                metadata={
                    "trace_id": norm_trace_id,
                    "request_id": norm_request_id,
                    "idempotency_key": norm_idempotency,
                    "local_order_id": local_order_id,
                    "broker_order_id": broker_order_id,
                    "error_code": error_code,
                },
            )
        )
        return payload

    def get_direct_order_trace(
        self,
        *,
        idempotency_key: str = "",
        local_order_id: str = "",
        client_order_id: str = "",
        request_id: str = "",
        trace_id: str = "",
    ) -> dict[str, Any] | None:
        trace = TradingLedger.get_direct_order_trace(
            idempotency_key=idempotency_key.strip(),
            local_order_id=local_order_id.strip(),
            client_order_id=client_order_id.strip(),
            request_id=request_id.strip(),
            trace_id=trace_id.strip(),
        )
        if not trace:
            return None
        local_id = str(trace.get("local_order_id", "") or "")
        if local_id:
            trade = TradingLedger.get_trade(local_id)
            if trade:
                trace["trade_status"] = trade.get("status", "")
                trace["filled_quantity"] = trade.get("filled_quantity", 0)
                trace["filled_price"] = trade.get("filled_price", 0.0)
        trace["trace"] = self._build_direct_trace(trace)
        effective_trace_id = str(
            (trace.get("response_payload", {}) or {}).get("trace_id", "")
            or (trace.get("trace", {}) or {}).get("trace_id", "")
            or trace_id
        )
        trace["trace_id"] = effective_trace_id
        if effective_trace_id:
            trace["trace_events"] = TradingLedger.list_ledger_entries(
                limit=100,
                trace_id=effective_trace_id,
            )
        else:
            trace["trace_events"] = []
        return trace

    async def run_batch(
        self,
        tickers: list[str],
        max_concurrency: int = 5,
        execute_orders: bool = True,
    ) -> list[dict[str, Any]]:
        semaphore = asyncio.Semaphore(max_concurrency)

        async def _run_single(symbol: str) -> dict[str, Any]:
            async with semaphore:
                try:
                    if execute_orders:
                        return await self.execute(symbol)
                    return await self.analyze(symbol)
                except TradingServiceError as exc:
                    return {"ticker": symbol, "error": {"code": exc.code, "message": exc.message, "details": exc.details}}
                except Exception as exc:  # noqa: BLE001
                    logger.exception("批量处理失败: ticker=%s err=%s", symbol, exc)
                    return {"ticker": symbol, "error": {"code": "INTERNAL_ERROR", "message": str(exc)}}

        tasks = [_run_single(ticker) for ticker in tickers]
        return await asyncio.gather(*tasks)

    async def get_balance(self) -> dict[str, Any]:
        account = await self._safe_get_balance()
        return asdict(account) if account else asdict(AccountBalance())

    async def get_positions(self) -> list[dict[str, Any]]:
        positions = await self._safe_get_positions()
        return [asdict(p) for p in positions]

    async def get_active_orders(self) -> list[dict[str, Any]]:
        return [asdict(order) for order in self.order_manager.active_orders.values()]

    async def cancel_active_orders(self, reason: str = "manual") -> dict[str, Any]:
        """批量撤销当前活动订单，并回写订单状态。"""
        await self._ensure_broker_connected()
        active_orders = list(self.order_manager.active_orders.items())
        if not active_orders:
            return {
                "channel": self.channel,
                "reason": str(reason or "manual"),
                "requested": 0,
                "cancelled": 0,
                "failed": 0,
                "items": [],
            }

        cancelled = 0
        failed = 0
        items: list[dict[str, Any]] = []
        for local_order_id, local_order in active_orders:
            candidate_ids = [str(local_order_id)]
            broker_order_id = self._extract_broker_order_id(getattr(local_order, "message", ""))
            if broker_order_id and broker_order_id not in candidate_ids:
                candidate_ids.append(broker_order_id)

            success = False
            last_error = ""
            used_order_id = candidate_ids[0]
            for candidate_id in candidate_ids:
                used_order_id = candidate_id
                try:
                    success = bool(await self.broker.cancel(candidate_id))
                except Exception as exc:  # noqa: BLE001
                    last_error = str(exc)
                    continue
                if success:
                    break

            if success:
                cancelled += 1
                local_order.status = OrderStatus.CANCELLED
                TradingLedger.update_trade_status(
                    trade_id=local_order_id,
                    status=OrderStatus.CANCELLED,
                    filled_price=float(getattr(local_order, "filled_price", 0.0) or 0.0),
                    filled_quantity=int(getattr(local_order, "filled_quantity", 0) or 0),
                )
                self.order_manager.active_orders.pop(local_order_id, None)
                if hasattr(self.order_manager, "_last_signatures"):
                    self.order_manager._last_signatures.pop(local_order_id, None)  # type: ignore[attr-defined]
                if hasattr(self.order_manager, "_broker_order_refs"):
                    self.order_manager._broker_order_refs.pop(local_order_id, None)  # type: ignore[attr-defined]
                items.append(
                    {
                        "order_id": str(local_order_id),
                        "ticker": str(getattr(local_order, "ticker", "")),
                        "status": "cancelled",
                        "used_order_id": used_order_id,
                    }
                )
            else:
                failed += 1
                items.append(
                    {
                        "order_id": str(local_order_id),
                        "ticker": str(getattr(local_order, "ticker", "")),
                        "status": "failed",
                        "used_order_id": used_order_id,
                        "error": last_error or "broker_cancel_failed",
                    }
                )

        TradingLedger.record_entry(
            LedgerEntry(
                category="SYSTEM",
                action="CANCEL_ACTIVE_ORDERS",
                detail=f"cancel_active_orders reason={reason}",
                status="success" if failed == 0 else "warning",
                metadata={
                    "channel": self.channel,
                    "reason": str(reason or "manual"),
                    "requested": len(active_orders),
                    "cancelled": cancelled,
                    "failed": failed,
                },
            )
        )
        return {
            "channel": self.channel,
            "reason": str(reason or "manual"),
            "requested": len(active_orders),
            "cancelled": cancelled,
            "failed": failed,
            "items": items,
        }

    async def switch_channel(self, target_channel: str, *, reconnect: bool = True) -> dict[str, Any]:
        """切换交易通道并重建执行组件。"""
        requested_raw = str(target_channel or "").strip().lower()
        alias_map = {"ths": "ths_auto"}
        requested_channel = alias_map.get(requested_raw, requested_raw)
        allowed_channels = {"simulation", "ths_auto", "ths_ipc", "qmt"}
        if requested_channel not in allowed_channels:
            raise TradingServiceError(
                code="INVALID_CHANNEL",
                message="unsupported trading channel",
                details={
                    "requested_channel": requested_channel,
                    "allowed_channels": sorted(list(allowed_channels)),
                },
                http_status=400,
            )

        previous_channel = self.channel
        if requested_channel == previous_channel:
            return {
                "changed": False,
                "requested_channel": requested_channel,
                "previous_channel": previous_channel,
                "active_channel": self.channel,
                "broker_connected": bool(getattr(getattr(self, "broker", None), "is_connected", False)),
            }

        previous_broker = self.broker
        previous_order_manager = self.order_manager
        previous_reconciliation_engine = self.reconciliation_engine
        try:
            await self._stop_order_sync_if_needed()
            if hasattr(previous_broker, "disconnect"):
                try:
                    await previous_broker.disconnect()
                except Exception:  # noqa: BLE001
                    pass

            self.channel = requested_channel
            self.broker = create_broker(requested_channel)
            self._rebind_execution_components()
            if reconnect:
                await self._ensure_broker_connected()

            payload = {
                "changed": True,
                "requested_channel": requested_channel,
                "previous_channel": previous_channel,
                "active_channel": self.channel,
                "broker_connected": bool(getattr(getattr(self, "broker", None), "is_connected", False)),
            }
            TradingLedger.record_entry(
                LedgerEntry(
                    category="SYSTEM",
                    action="TRADING_CHANNEL_SWITCHED",
                    detail=f"switch channel {previous_channel} -> {self.channel}",
                    metadata=payload,
                )
            )
            return payload
        except TradingServiceError:
            self.channel = previous_channel
            self.broker = previous_broker
            self.order_manager = previous_order_manager
            self.reconciliation_engine = previous_reconciliation_engine
            if self._initialized:
                self._start_order_sync_if_needed()
            raise
        except Exception as exc:  # noqa: BLE001
            self.channel = previous_channel
            self.broker = previous_broker
            self.order_manager = previous_order_manager
            self.reconciliation_engine = previous_reconciliation_engine
            if self._initialized:
                self._start_order_sync_if_needed()
            raise TradingServiceError(
                code="CHANNEL_SWITCH_FAILED",
                message="failed to switch trading channel",
                details={
                    "requested_channel": requested_channel,
                    "previous_channel": previous_channel,
                    "error": str(exc),
                },
                http_status=500,
            ) from exc

    async def get_trade_snapshot(self, include_channel_raw: bool = True) -> dict[str, Any]:
        await self._ensure_broker_connected()
        balance = await self._safe_get_balance()
        positions = await self._safe_get_positions()
        orders = await self.broker.get_orders()
        balance_payload = asdict(balance)
        positions_payload = [asdict(item) for item in positions]
        orders_payload = [asdict(item) for item in orders]

        total_value = _to_float(balance_payload.get("total_assets", 0.0))
        daily_pnl = _to_float(balance_payload.get("daily_pnl", 0.0))
        holding_value = _to_float(balance_payload.get("market_value", 0.0))
        cash = _to_float(balance_payload.get("available_cash", 0.0))

        strategies: list[dict[str, Any]] = []
        for pos in positions_payload:
            market_value = _to_float(pos.get("market_value", 0.0))
            unrealized_pnl = _to_float(pos.get("unrealized_pnl", 0.0))
            daily_return = unrealized_pnl / market_value if market_value > 0 else 0.0
            strategies.append(
                {
                    "name": str(pos.get("ticker", "")).upper(),
                    "quality_score": 0.0,
                    "status": "holding",
                    "daily_return": daily_return,
                    "market_value": market_value,
                }
            )

        payload: dict[str, Any] = {
            "channel": self.channel,
            "broker_connected": bool(getattr(getattr(self, "broker", None), "is_connected", False)),
            "channel_info": self.broker.check_health() if hasattr(self.broker, "check_health") else {},
            "balance": balance_payload,
            "positions": positions_payload,
            "orders": orders_payload,
            "reconciliation_guard": self.get_reconciliation_guard_state(),
            "counts": {
                "positions": len(positions),
                "orders": len(orders),
            },
            # 向后兼容旧版 Dashboard 字段
            "total_value": total_value,
            "daily_pnl": daily_pnl,
            "holding_value": holding_value,
            "cash": cash,
            "strategies": strategies,
        }

        if include_channel_raw and hasattr(self.broker, "get_trade_snapshot"):
            try:
                raw = await self.broker.get_trade_snapshot()  # type: ignore[attr-defined]
            except Exception as exc:  # noqa: BLE001
                payload["channel_raw"] = {"status": "error", "message": str(exc)}
            else:
                payload["channel_raw"] = self._json_safe(raw)

        return payload

    async def sync_orders_now(self) -> dict[str, Any]:
        await self._ensure_broker_connected()
        stats = await self.order_manager.sync_now()
        return {"channel": self.channel, "stats": stats}

    async def reconcile(self, initial_cash: Optional[float] = None) -> dict[str, Any]:
        await self._ensure_broker_connected()
        seed_cash = initial_cash if initial_cash is not None else self._default_initial_cash()
        report = await self.reconciliation_engine.run(initial_cash=seed_cash)
        self.recon_guard.handle_reconciliation_result(report)
        return report

    async def day_roll(self, reason: str = "manual", force: bool = False) -> dict[str, Any]:
        """
        执行交易日日切：
        - 非交易日默认跳过
        - 重置风控日内状态
        - 模拟盘执行 T+1 可卖切换
        - 订单管理器清理同步签名
        - 触发一次对账并更新阻断状态
        """
        today = self.calendar.today()
        if not force and not self.calendar.is_trading_day(today):
            result = {
                "skipped": True,
                "code": "NON_TRADING_DAY",
                "reason": reason,
                "date": str(today),
                "next_trading_day": str(self.calendar.next_trading_day(today)),
            }
            TradingLedger.record_entry(
                LedgerEntry(
                    category="SYSTEM",
                    action="DAY_ROLL_SKIP",
                    detail=f"day_roll skipped on non-trading day: {today}",
                    metadata=result,
                )
            )
            return result

        await self._ensure_broker_connected()
        self.risk_gate.reset_daily()
        self.order_manager.on_day_roll()

        broker_new_day = False
        if hasattr(self.broker, "new_day"):
            try:
                self.broker.new_day()
                broker_new_day = True
            except Exception as exc:  # noqa: BLE001
                logger.warning("执行 broker.new_day 失败: %s", exc)

        if self.channel == "simulation":
            self.simulation_days += 1

        recon = await self.reconcile()
        TradingLedger.record_entry(
            LedgerEntry(
                category="SYSTEM",
                action="DAY_ROLL",
                detail=f"day_roll reason={reason}",
                metadata={
                    "reason": reason,
                    "force": force,
                    "channel": self.channel,
                    "simulation_days": self.simulation_days,
                    "broker_new_day": broker_new_day,
                    "reconciliation_status": recon.get("status", "unknown"),
                    "reconciliation_code": recon.get("code", ""),
                },
            )
        )
        return {
            "skipped": False,
            "channel": self.channel,
            "simulation_days": self.simulation_days,
            "broker_new_day": broker_new_day,
            "reconciliation": recon,
        }

    async def _ensure_broker_connected(self):
        if getattr(self.broker, "is_connected", False):
            return

        max_retries = 3
        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                if await self.broker.connect():
                    return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning("连接交易通道失败 (第 %d/%d 次): channel=%s err=%s", attempt, max_retries, self.channel, exc)
            if attempt < max_retries:
                await asyncio.sleep(2)

        if self.channel != "simulation":
            logger.warning("交易通道 %s 连续 %d 次连接失败，降级至 simulation。last_error=%s", self.channel, max_retries, last_error)
            self.channel = "simulation"
            self.broker = create_broker("simulation")
            await self.broker.connect()
            self._rebind_execution_components()
            return

        raise TradingServiceError(
            code="BROKER_UNAVAILABLE",
            message="simulation 通道连接失败。",
            details={"channel": self.channel},
            http_status=503,
        )

    async def _safe_get_balance(self) -> AccountBalance:
        try:
            await self._ensure_broker_connected()
            return await self.broker.get_balance()
        except Exception as exc:  # noqa: BLE001
            logger.warning("获取资金失败，使用默认账户快照: %s", exc)
            return AccountBalance(
                total_assets=self._default_initial_cash(),
                available_cash=self._default_initial_cash(),
                frozen_cash=0.0,
                market_value=0.0,
            )

    async def _safe_get_positions(self) -> list[Position]:
        try:
            await self._ensure_broker_connected()
            return await self.broker.get_positions()
        except Exception as exc:  # noqa: BLE001
            logger.warning("获取持仓失败，返回空持仓: %s", exc)
            return []

    async def _build_context(self, ticker: str) -> dict[str, Any]:
        account = await self._safe_get_balance()
        positions = await self._safe_get_positions()
        position_map = {
            item.ticker: {
                "quantity": item.quantity,
                "available": item.available,
                "avg_cost": item.avg_cost,
                "market_value": item.market_value,
            }
            for item in positions
        }

        context: dict[str, Any] = {
            "portfolio": {
                "balance": account.available_cash,
                "total_assets": account.total_assets,
                "positions": position_map,
            },
            "fundamentals": {},
            "technical_indicators": {},
            "news_sentiment": {"status": "no_news", "sentiment_score": 50.0},
            "realtime": {},
        }

        await self._inject_china_data_context(ticker, context)
        await self._inject_news_context(ticker, context)
        self._inject_dataflow_context_snapshot(context)
        self._inject_llm_context_snapshot(context)
        return context

    async def _inject_china_data_context(self, ticker: str, context: dict[str, Any]):
        if self._china_data_disabled:
            return
        if self._china_data is None:
            try:
                from src.dataflows.china_data import ChinaDataAssembler

                self._china_data = ChinaDataAssembler()
            except Exception as exc:  # noqa: BLE001
                logger.warning("ChinaDataAssembler 初始化失败，将禁用该数据源: %s", exc)
                self._china_data_disabled = True
                return

        try:
            assembler_data = await asyncio.to_thread(self._china_data.fetch_agent_context, ticker)
            context["technical_indicators"] = assembler_data.get("technical_indicators", {})
            context["realtime"] = assembler_data.get("realtime", {})
        except Exception as exc:  # noqa: BLE001
            logger.warning("A 股数据构建失败，降级为空上下文: %s", exc)

    async def _inject_news_context(self, ticker: str, context: dict[str, Any]):
        try:
            from src.dataflows.news.unified import UnifiedNewsTool

            news_result = await UnifiedNewsTool.get_analyzed_news(ticker, limit=5)
            context["news_sentiment"] = news_result
        except Exception as exc:  # noqa: BLE001
            logger.warning("新闻数据构建失败，降级 no_news: %s", exc)

    def _inject_dataflow_context_snapshot(self, context: dict[str, Any]) -> None:
        if getattr(self, "_china_data_disabled", False):
            context["dataflow_quality"] = {}
            context["dataflow_summary"] = {}
            context["dataflow_tuning"] = {}
            context["dataflow_runtime_config"] = {}
            return

        try:
            from src.dataflows.source_manager import data_manager

            metrics = data_manager.get_metrics()
            context["dataflow_quality"] = self._json_safe(metrics.get("quality", {}))
            context["dataflow_summary"] = self._json_safe(metrics.get("summary", {}))
            context["dataflow_tuning"] = self._json_safe(metrics.get("tuning", {}))
            context["dataflow_runtime_config"] = self._json_safe(metrics.get("runtime_config", {}))
        except Exception as exc:  # noqa: BLE001
            context["dataflow_quality"] = {
                "alert_level": "unknown",
                "code": "DATAFLOW_SNAPSHOT_UNAVAILABLE",
                "error": str(exc),
            }
            context["dataflow_summary"] = {}
            context["dataflow_tuning"] = {}
            context["dataflow_runtime_config"] = {}

    def _inject_llm_context_snapshot(self, context: dict[str, Any]) -> None:
        try:
            usage_summary = TradingLedger.get_llm_usage_summary(hours=24)
            runtime = get_llm_runtime_metrics()
            context["llm_usage_summary"] = self._json_safe(usage_summary)
            context["llm_runtime"] = self._json_safe(runtime)
        except Exception as exc:  # noqa: BLE001
            context["llm_usage_summary"] = {"error": str(exc)}
            context["llm_runtime"] = {"error": str(exc)}

    def _build_order_request(self, state: dict[str, Any]) -> Optional[OrderRequest]:
        ticker = state.get("ticker", "")
        decision_data = state.get("trading_decision", {})
        action = str(decision_data.get("action", state.get("decision", "HOLD"))).upper()
        percentage = _to_float(decision_data.get("percentage", 0.0))
        if action not in {"BUY", "SELL"} or percentage <= 0:
            return None

        context = state.get("context", {})
        realtime = context.get("realtime", {})
        price = _to_float(realtime.get("price", 0.0))
        if price <= 0:
            price = _to_float(decision_data.get("price", 0.0))
        if price <= 0:
            return None

        portfolio = context.get("portfolio", {})
        positions = portfolio.get("positions", {})
        position_info = positions.get(ticker, {})
        quantity = 0
        if action == "BUY":
            available_cash = _to_float(portfolio.get("balance", 0.0))
            budget = available_cash * (percentage / 100.0)
            quantity = int(budget / price)
        elif action == "SELL":
            current_quantity = int(_to_float(position_info.get("available", position_info.get("quantity", 0))))
            quantity = int(current_quantity * (percentage / 100.0))

        quantity = (quantity // 100) * 100  # A 股手数约束
        if quantity <= 0:
            return None

        return OrderRequest(
            ticker=ticker,
            side=OrderSide.BUY if action == "BUY" else OrderSide.SELL,
            price=round(price, 3),
            quantity=quantity,
            market="CN",
            memo=str(decision_data.get("reason", "")),
        )

    def _ensure_state_trace(self, state: dict[str, Any], *, phase: str) -> None:
        session_id = str(state.get("session_id", "") or "")
        trace_id = str(state.get("trace_id", "") or "")
        if not trace_id:
            trace_id = f"trace-{uuid.uuid4().hex[:12]}"
            state["trace_id"] = trace_id

        request_id = str(state.get("request_id", "") or "")
        context = state.get("context", {}) if isinstance(state.get("context", {}), dict) else {}
        if not request_id:
            request_id = str(context.get("request_id", "") or "")
        if not request_id and session_id:
            request_id = session_id
        state["request_id"] = request_id

        trace = state.get("trace", {}) if isinstance(state.get("trace", {}), dict) else {}
        trace.update(
            {
                "trace_id": trace_id,
                "request_id": request_id,
                "session_id": session_id,
                "phase": phase,
                "channel": self.channel,
                "ticker": str(state.get("ticker", "") or ""),
            }
        )
        state["trace"] = trace

    def _annotate_policy_snapshot(self, state: dict[str, Any]) -> None:
        existing = state.get("degrade_policy", {}) if isinstance(state.get("degrade_policy", {}), dict) else {}
        if existing.get("policy_version"):
            return
        meta = self.degrade_policy.describe()
        state["degrade_policy"] = {
            **meta,
            "rules_evaluated": 0,
            "matched_count": 0,
            "matched_rules": [],
            "selected_rules": [],
            "degrade_flags": [],
            "recommended_action": "none",
            "should_force_hold": False,
            "should_warn": False,
            "should_degrade": False,
            "errors": [],
            "budget_recovery_guard": self.get_budget_recovery_guard_state(),
        }

    def _persist_analysis_reports(self, ticker: str, state: dict[str, Any]):
        reports = state.get("analysis_reports", {})
        decision = state.get("decision", "HOLD")
        confidence = _to_float(state.get("confidence", 0.0))
        for report_type, report_value in reports.items():
            report_payload = (
                report_value.model_dump()
                if hasattr(report_value, "model_dump")
                else dict(report_value)
                if isinstance(report_value, dict)
                else report_value
            )
            TradingLedger.record_analysis(
                AnalysisReport(
                    ticker=ticker,
                    report_type=report_type,
                    content=str(report_payload),
                    decision=decision,
                    confidence=confidence,
                    metadata={"session_id": state.get("session_id", "")},
                )
            )

    def _persist_decision_evidence(
        self,
        *,
        ticker: str,
        state: dict[str, Any],
        phase: str,
        risk_check: dict[str, Any],
        order: dict[str, Any] | None,
    ) -> None:
        try:
            self._ensure_state_trace(state, phase=phase)
            self._annotate_policy_snapshot(state)
            decision_payload = state.get("trading_decision", {})
            context = state.get("context", {})
            trace = state.get("trace", {}) if isinstance(state.get("trace", {}), dict) else {}
            request_id = str(state.get("request_id", "") or trace.get("request_id", ""))
            llm_runtime = get_llm_runtime_metrics()
            evidence = {
                "evidence_version": "2026.04.08.1",
                "timestamp": time.time(),
                "phase": phase,
                "session_id": str(state.get("session_id", "")),
                "request_id": request_id,
                "ticker": ticker,
                "channel": self.channel,
                "decision": str(state.get("decision", "HOLD")),
                "confidence": _to_float(state.get("confidence", 0.0)),
                "action": str(decision_payload.get("action", state.get("decision", "HOLD"))).upper(),
                "percentage": _to_float(decision_payload.get("percentage", 0.0)),
                "reason": str(decision_payload.get("reason", "")),
                "trace": {
                    "trace_id": str(trace.get("trace_id", state.get("trace_id", ""))),
                    "request_id": request_id,
                    "session_id": str(trace.get("session_id", state.get("session_id", ""))),
                    "phase": str(trace.get("phase", phase)),
                    "channel": str(trace.get("channel", self.channel)),
                    "ticker": str(trace.get("ticker", ticker)),
                    "order_id": str((order or {}).get("order_id", "")),
                    "broker_order_id": str((order or {}).get("broker_order_id", "")),
                },
                "risk_check": risk_check or {},
                "order": order or {},
                "analysis_reports": self._compact_reports(state.get("analysis_reports", {})),
                "debate_results": state.get("debate_results", {}),
                "degrade_flags": state.get("degrade_flags", []),
                "degrade_warnings": state.get("degrade_warnings", []),
                "degrade_policy": self._json_safe(state.get("degrade_policy", {})),
                "budget_recovery_guard": self._json_safe(self.get_budget_recovery_guard_state()),
                "reconciliation_guard": self._json_safe(self.get_reconciliation_guard_state()),
                "llm_runtime": self._json_safe(llm_runtime),
                "context_digest": {
                    "portfolio": context.get("portfolio", {}),
                    "realtime": context.get("realtime", {}),
                    "news_sentiment": context.get("news_sentiment", {}),
                    "dataflow_quality": context.get("dataflow_quality", {}),
                    "dataflow_summary": context.get("dataflow_summary", {}),
                    "dataflow_tuning": context.get("dataflow_tuning", {}),
                    "llm_usage_summary": context.get("llm_usage_summary", {}),
                    "llm_runtime": context.get("llm_runtime", {}),
                    "technical_keys": sorted(list((context.get("technical_indicators") or {}).keys()))[:20],
                    "fundamental_keys": sorted(list((context.get("fundamentals") or {}).keys()))[:20],
                },
            }
            normalized, missing = self._normalize_evidence_payload(
                evidence,
                fallback_trace_id=str(trace.get("trace_id", state.get("trace_id", ""))),
                fallback_request_id=request_id,
            )
            if missing:
                TradingLedger.record_entry(
                    LedgerEntry(
                        category="SYSTEM",
                        level="WARNING",
                        action="EVIDENCE_SCHEMA_PATCHED",
                        detail=f"patched missing evidence fields: {len(missing)}",
                        status="warning",
                        metadata={
                            "phase": phase,
                            "ticker": ticker,
                            "request_id": request_id,
                            "trace_id": str(normalized.get("trace", {}).get("trace_id", "")),
                            "missing_paths": missing,
                        },
                    )
                )
            TradingLedger.record_decision_evidence(normalized)
        except Exception as exc:  # noqa: BLE001
            logger.debug("persist decision evidence skipped: %s", exc)

    def _apply_failure_degrade(self, state: dict[str, Any]) -> None:
        self._ensure_state_trace(state, phase="execute")
        evaluation = self.degrade_policy.evaluate(state)
        evaluation = self._apply_budget_recovery_guard(state, evaluation)
        state["degrade_policy"] = evaluation
        reasons = list(evaluation.get("degrade_flags", []))
        if not evaluation.get("should_degrade", False):
            state["degrade_flags"] = []
            state["degrade_warnings"] = []
            return

        ticker = str(state.get("ticker", ""))
        prior_action = str(
            state.get("trading_decision", {}).get("action", state.get("decision", "HOLD"))
        ).upper()
        detail_items = [
            "{rule_id}({detail})".format(
                rule_id=str(item.get("rule_id", "")),
                detail=str(item.get("detail", "")),
            )
            for item in evaluation.get("selected_rules", [])
        ]
        reason_text = "degraded safety guard: " + "; ".join(detail_items or reasons)
        recommended_action = str(evaluation.get("recommended_action", "none"))

        if recommended_action == "warn_only":
            state["degrade_flags"] = []
            state["degrade_warnings"] = reasons
            TradingLedger.record_entry(
                LedgerEntry(
                    category="SYSTEM",
                    level="WARNING",
                    action="DEGRADE_WARN",
                    detail=f"degrade warn on context: {ticker}",
                    status="warning",
                    metadata={
                        "ticker": ticker,
                        "reasons": reasons,
                        "prior_action": prior_action,
                        "channel": self.channel,
                        "session_id": str(state.get("session_id", "")),
                        "trace_id": str(state.get("trace_id", "")),
                        "degrade_policy": evaluation,
                    },
                )
            )
            return

        state["degrade_flags"] = reasons
        state["degrade_warnings"] = []
        state["decision"] = "HOLD"
        state["confidence"] = min(_to_float(state.get("confidence", 0.0)), 35.0)
        state["trading_decision"] = {
            "action": "HOLD",
            "percentage": 0.0,
            "reason": reason_text,
            "confidence": state.get("confidence", 0.0),
        }

        TradingLedger.record_entry(
            LedgerEntry(
                category="SYSTEM",
                level="WARNING",
                action="DEGRADE_HOLD",
                detail=f"force HOLD on degraded context: {ticker}",
                status="degraded",
                metadata={
                    "ticker": ticker,
                    "reasons": reasons,
                    "prior_action": prior_action,
                    "channel": self.channel,
                    "session_id": str(state.get("session_id", "")),
                    "trace_id": str(state.get("trace_id", "")),
                    "degrade_policy": evaluation,
                },
            )
        )

    def _apply_budget_recovery_guard(self, state: dict[str, Any], evaluation: dict[str, Any]) -> dict[str, Any]:
        """
        架构审计优化：委托 BudgetRecoveryGuard 处理预算逻辑。
        """
        context = state.get("context", {}) if isinstance(state.get("context", {}), dict) else {}
        usage_summary = context.get("llm_usage_summary", {}) if isinstance(context.get("llm_usage_summary", {}), dict) else {}
        current_cost = _to_float(usage_summary.get("cost_usd", 0.0))
        budget = _to_float(os.getenv("LLM_DAILY_BUDGET_USD", "0"))
        
        self.budget_guard.update_state(current_cost, budget)
        guard_state = self.budget_guard.get_status()
        
        evaluation["budget_recovery_guard"] = guard_state
        
        if guard_state["active"]:
            action = guard_state["action"]
            evaluation["selected_rules"].append({
                "rule_id": "llm_budget_recovery_guard",
                "description": "keep degraded while budget recovery guard is active",
                "severity": "critical" if action == "force_hold" else "warn",
                "action": action,
                "priority": 9999,
                "detail": f"Cost ¥{current_cost:.4f} triggered protection",
            })
            evaluation["should_degrade"] = True
            evaluation["recommended_action"] = action
            evaluation["degrade_flags"].append("budget_protection")
            
        return evaluation

    def _collect_degrade_reasons(self, state: dict[str, Any]) -> list[str]:
        evaluation = self.degrade_policy.evaluate(state)
        return list(evaluation.get("degrade_flags", []))

    def _enforce_direct_order_safety(
        self,
        *,
        ticker: str,
        side: str,
        quantity: int,
        price: float,
        manual_confirm: bool,
        manual_confirm_token: str,
    ) -> float:
        """
        架构审计优化：委托 DirectOrderGuard 进行安全检查。
        """
        ok, reason = self.direct_guard.check(
            ticker=ticker,
            side=side,
            price=price,
            quantity=quantity,
            manual_confirm=manual_confirm,
            confirm_token=manual_confirm_token,
        )
        if not ok:
            # 映射错误码以保持兼容性
            code = "DIRECT_ORDER_GUARD_VIOLATION"
            if "频率" in reason:
                code = "DIRECT_ORDER_RATE_LIMITED"
            elif "白名单" in reason:
                code = "DIRECT_ORDER_TICKER_NOT_ALLOWED"
            elif "单笔" in reason:
                code = "DIRECT_ORDER_NOTIONAL_LIMIT"
            elif "今日累计" in reason:
                code = "DIRECT_ORDER_DAILY_LIMIT_EXCEEDED"
            elif "交易日" in reason or "窗口" in reason:
                code = "DIRECT_ORDER_WINDOW_CLOSED"
            elif "人工确认" in reason:
                code = "DIRECT_ORDER_MANUAL_CONFIRM_REQUIRED"

            raise TradingServiceError(
                code=code,
                message=reason,
                http_status=403 if "CONFIRM" in code else 409 if "LIMIT" in code or "WINDOW" in code else 429,
            )

        return max(0.0, float(quantity) * float(price))

    @staticmethod
    def _normalize_degrade_action(action: str) -> str:
        value = str(action or "").strip().lower()
        if value in {"force_hold", "warn_only", "none"}:
            return value
        return "force_hold"

    @staticmethod
    def _compact_reports(reports: dict[str, Any]) -> dict[str, Any]:
        compact: dict[str, Any] = {}
        for key, value in (reports or {}).items():
            if hasattr(value, "model_dump"):
                payload = value.model_dump()
            elif isinstance(value, dict):
                payload = dict(value)
            else:
                payload = {"raw": str(value)}

            compact[key] = {
                "summary": payload.get("summary", ""),
                "stance": payload.get("stance", ""),
                "score": payload.get("score", 0),
                "key_factors": payload.get("key_factors", []),
            }
        return compact

    @staticmethod
    def _json_safe(value: Any) -> Any:
        if value is None:
            return None
        if hasattr(value, "model_dump"):
            return TradingService._json_safe(value.model_dump())
        if hasattr(value, "__dataclass_fields__"):
            return TradingService._json_safe(asdict(value))
        if isinstance(value, dict):
            return {str(k): TradingService._json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [TradingService._json_safe(v) for v in value]
        if hasattr(value, "value"):
            return value.value
        if hasattr(value, "isoformat"):
            try:
                return value.isoformat()
            except Exception:  # noqa: BLE001
                return str(value)
        item = getattr(value, "item", None)
        if callable(item):
       
            try:
                return item()
            except Exception:  # noqa: BLE001
                return str(value)
        return value

    def _normalize_evidence_payload(
        self,
        payload: dict[str, Any],
        *,
        fallback_trace_id: str,
        fallback_request_id: str,
    ) -> tuple[dict[str, Any], list[str]]:
        evidence = dict(payload or {})
        evidence.setdefault("evidence_version", "2026.04.09.1")
        evidence.setdefault("analysis_reports", {})
        evidence.setdefault("debate_results", {})
        evidence.setdefault("risk_check", {})
        evidence.setdefault("degrade_flags", [])
        evidence.setdefault("degrade_warnings", [])
        evidence.setdefault("degrade_policy", {})
        evidence.setdefault("budget_recovery_guard", {})
        evidence.setdefault("context_digest", {})
        evidence.setdefault("llm_runtime", {})

        trace = evidence.get("trace", {}) if isinstance(evidence.get("trace", {}), dict) else {}
        trace.setdefault("trace_id", str(fallback_trace_id or fallback_request_id))
        trace.setdefault("request_id", str(fallback_request_id))
        evidence["trace"] = trace
        evidence.setdefault("request_id", str(fallback_request_id))

        missing = [path for path in EVIDENCE_REQUIRED_PATHS if not self._has_required_path(evidence, path)]
        return evidence, missing

    @staticmethod
    def _has_required_path(payload: dict[str, Any], path: str) -> bool:
        cursor: Any = payload
        for part in path.split("."):
            if not isinstance(cursor, dict) or part not in cursor:
                return False
            cursor = cursor.get(part)
        if cursor is None:
            return False
        if isinstance(cursor, str):
            return cursor.strip() != ""
        return True

    def _persist_trade(self, state: dict[str, Any], order: Any):
        if order.status in {OrderStatus.FAILED, OrderStatus.REJECTED}:
            return

        trade_kwargs = {
            "ticker": order.ticker,
            "action": order.side.value,
            "price": order.price,
            "filled_price": order.filled_price or order.price,
            "quantity": order.quantity,
            "filled_quantity": order.filled_quantity or order.quantity,
            "amount": order.amount or (order.price * order.quantity),
            "commission": order.commission,
            "confidence": _to_float(state.get("confidence", 0.0)),
            "session_id": state.get("session_id", ""),
            "channel": order.channel,
            "status": order.status.value if hasattr(order.status, "value") else str(order.status),
            "metadata": {"decision": state.get("decision", "HOLD")},
        }
        if getattr(order, "order_id", ""):
            trade_kwargs["id"] = order.order_id
        TradingLedger.record_trade(TradeRecord(**trade_kwargs))

    def _persist_direct_trade(
        self,
        *,
        order: Any,
        trace: dict[str, Any],
        request_payload: dict[str, Any],
        idempotency_key: str,
        request_id: str,
    ) -> None:
        trade_kwargs = {
            "ticker": order.ticker,
            "action": order.side.value if hasattr(order.side, "value") else str(order.side),
            "price": order.price,
            "filled_price": order.filled_price or order.price,
            "quantity": order.quantity,
            "filled_quantity": order.filled_quantity or 0,
            "amount": order.amount or (order.price * order.quantity),
            "commission": order.commission,
            "confidence": 0.0,
            "session_id": request_id,
            "channel": order.channel or self.channel,
            "status": order.status.value if hasattr(order.status, "value") else str(order.status),
            "metadata": {
                "decision": "DIRECT",
                "request_id": request_id,
                "idempotency_key": idempotency_key,
                "trace": trace,
                "request_payload": request_payload,
            },
        }
        if getattr(order, "order_id", ""):
            trade_kwargs["id"] = order.order_id
        TradingLedger.record_trade(TradeRecord(**trade_kwargs))

    def _persist_direct_order_evidence(
        self,
        *,
        request_id: str,
        idempotency_key: str,
        client_order_id: str,
        ticker: str,
        side: str,
        channel: str,
        risk_check: dict[str, Any],
        order: dict[str, Any] | None,
        trace: dict[str, Any],
        status: str,
        error: str = "",
        request_payload: dict[str, Any],
        trace_id: str,
    ) -> str:
        try:
            evidence = {
                "evidence_version": "2026.04.08.1",
                "timestamp": time.time(),
                "phase": "direct_order",
                "session_id": request_id,
                "request_id": request_id,
                "ticker": ticker,
                "channel": channel,
                "decision": "DIRECT",
                "confidence": 0.0,
                "action": side.upper(),
                "percentage": 0.0,
                "reason": f"direct_order_status:{status}",
                "risk_check": risk_check or {},
                "order": order or {},
                "analysis_reports": {},
                "debate_results": {},
                "degrade_flags": [],
                "degrade_policy": self._json_safe(self.degrade_policy.describe()),
                "budget_recovery_guard": self._json_safe(self.get_budget_recovery_guard_state()),
                "reconciliation_guard": self._json_safe(self.get_reconciliation_guard_state()),
                "trace": {
                    "trace_id": str(trace_id or trace.get("trace_id", "") or request_id),
                    "request_id": request_id,
                    "session_id": request_id,
                    "phase": "direct_order",
                    "channel": channel,
                    "ticker": ticker,
                    "idempotency_key": idempotency_key,
                    "client_order_id": client_order_id,
                    "local_order_id": str(trace.get("local_order_id", "")),
                    "broker_order_id": str(trace.get("broker_order_id", "")),
                    "status": status,
                },
                "request_payload": request_payload,
                "idempotency_key": idempotency_key,
                "client_order_id": client_order_id,
                "status": status,
                "llm_runtime": self._json_safe(get_llm_runtime_metrics()),
                "context_digest": {
                    "portfolio": {},
                    "realtime": {},
                    "news_sentiment": {},
                    "dataflow_quality": {},
                    "dataflow_summary": {},
                    "dataflow_tuning": {},
                    "technical_keys": [],
                    "fundamental_keys": [],
                },
            }
            normalized, missing = self._normalize_evidence_payload(
                evidence,
                fallback_trace_id=str(trace_id or trace.get("trace_id", "") or request_id),
                fallback_request_id=request_id,
            )
            if missing:
                TradingLedger.record_entry(
                    LedgerEntry(
                        category="SYSTEM",
                        level="WARNING",
                        action="EVIDENCE_SCHEMA_PATCHED",
                        detail=f"patched missing direct_order evidence fields: {len(missing)}",
                        status="warning",
                        metadata={
                            "phase": "direct_order",
                            "ticker": ticker,
                            "request_id": request_id,
                            "trace_id": str(normalized.get("trace", {}).get("trace_id", "")),
                            "missing_paths": missing,
                        },
                    )
                )
            return TradingLedger.record_decision_evidence(normalized)
        except Exception as exc:  # noqa: BLE001
            logger.debug("persist direct order evidence skipped: %s", exc)
            return ""

    @staticmethod
    def _direct_order_signature_match(existing: dict[str, Any], incoming: dict[str, Any]) -> bool:
        compare_fields = ("channel", "ticker", "side", "quantity", "price", "order_type")
        for key in compare_fields:
            left = existing.get(key, "")
            right = incoming.get(key, "")
            if key in {"quantity"}:
                if int(left or 0) != int(right or 0):
                    return False
                continue
            if key in {"price"}:
                if round(float(left or 0.0), 6) != round(float(right or 0.0), 6):
                    return False
                continue
            if str(left or "").strip().lower() != str(right or "").strip().lower():
                return False

        existing_client = str(existing.get("client_order_id", "") or "").strip()
        incoming_client = str(incoming.get("client_order_id", "") or "").strip()
        if existing_client and incoming_client and existing_client != incoming_client:
            return False
        return True

    @staticmethod
    def _build_direct_trace(record: dict[str, Any]) -> dict[str, Any]:
        payload = record.get("response_payload", {}) if isinstance(record.get("response_payload", {}), dict) else {}
        payload_trace = payload.get("trace", {}) if isinstance(payload.get("trace", {}), dict) else {}
        return {
            "trace_id": str(payload.get("trace_id", "") or payload_trace.get("trace_id", "")),
            "request_id": str(record.get("request_id", "") or ""),
            "idempotency_key": str(record.get("idempotency_key", "") or ""),
            "channel": str(record.get("channel", "") or ""),
            "client_order_id": str(record.get("client_order_id", "") or ""),
            "local_order_id": str(record.get("local_order_id", "") or ""),
            "broker_order_id": str(record.get("broker_order_id", "") or ""),
            "status": str(record.get("status", "") or ""),
        }

    @staticmethod
    def _extract_broker_order_id(message: str) -> str:
        text = str(message or "")
        marker = "broker_order_id="
        if marker not in text:
            return ""
        return text.split(marker, 1)[1].split(";", 1)[0].strip()

    def _create_vm_with_fallback(self):
        try:
            from src.core.trading_vm import TradingVM

            return TradingVM()
        except Exception as exc:  # noqa: BLE001
            logger.warning("TradingVM 初始化失败，已降级到 FallbackVM: %s", exc)
            return _FallbackVM()

    def _default_initial_cash(self) -> float:
        return float(os.getenv("SIM_INITIAL_BALANCE", "1000000"))

    def _rebind_execution_components(self):
        self.order_manager.stop_sync_loop()
        if self._order_sync_task and not self._order_sync_task.done():
            self._order_sync_task.cancel()
        self._order_sync_task = None
        self.order_manager = OrderManager(self.broker)
        self.reconciliation_engine = ReconciliationEngine(self.broker)
        if self._initialized:
            self._start_order_sync_if_needed()

    def _start_order_sync_if_needed(self):
        if not self._order_sync_enabled:
            return
        if self._order_sync_task and not self._order_sync_task.done():
            return
        self._order_sync_task = asyncio.create_task(
            self.order_manager.start_sync_loop(interval=self._order_sync_interval)
        )

    async def _stop_order_sync_if_needed(self):
        self.order_manager.stop_sync_loop()
        task = self._order_sync_task
        if task and not task.done():
            try:
                await asyncio.wait_for(task, timeout=1.5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                task.cancel()
            except Exception:  # noqa: BLE001
                task.cancel()
        self._order_sync_task = None

    def unlock_reconciliation_block(
        self,
        reason: str = "manual",
        operator: str = "api",
        source_ip: str = "",
        user_agent: str = "",
    ) -> dict[str, Any]:
        """
        架构审计优化：委托 ReconciliationGuard 解除阻断。
        """
        was_blocked = self.recon_guard.blocked
        self.recon_guard.unblock(reason=reason, operator=operator)

        TradingLedger.record_entry(
            LedgerEntry(
                category="SYSTEM",
                action="RECON_UNLOCK",
                detail="reconciliation guard manually unlocked",
                metadata={
                    "mode": "manual",
                    "reason": reason,
                    "operator": operator,
                    "source_ip": source_ip,
                    "user_agent": user_agent,
                    "was_blocked": was_blocked,
                },
            )
        )
        return {
            "was_blocked": was_blocked,
            "reason": reason,
            "operator": operator,
            "guard": self.recon_guard.get_status(),
        }

    def get_runtime_state(self) -> dict[str, Any]:
        """
        架构审计优化：聚合各模块状态，提供统一的系统运行时视图。
        """
        today = self.calendar.today()
        
        # 1. 采集基础指标
        llm_usage_summary = TradingLedger.get_llm_usage_summary(hours=24)
        
        # 2. 采集数据流指标
        dataflow_metrics = {}
        dataflow_summary = {}
        try:
            from src.dataflows.source_manager import data_manager
            dataflow_metrics = data_manager.get_metrics()
            dataflow_summary = dataflow_metrics.get("summary", {})
        except Exception:
            pass

        # 3. 聚合全量状态
        return {
            "channel": self.channel,
            "broker_connected": bool(getattr(getattr(self, "broker", None), "is_connected", False)),
            "order_sync_enabled": self._order_sync_enabled,
            "direct_order_guard": self.direct_guard.get_status(),
            "risk": self.risk_gate.get_metrics(),
            "degrade_policy": self.degrade_policy.describe(),
            "budget_recovery_guard": self.budget_guard.get_status(),
            "budget_recovery_metrics": self.budget_guard.get_status().get("metrics", {}),
            "reconciliation_guard": self.recon_guard.get_status(),
            "dataflow": dataflow_metrics,
            "dataflow_summary": dataflow_summary,
            "dataflow_tuning": dataflow_metrics.get("tuning", {"action": "none", "quality_alert_level": "ok", "suggestions": []}),
            "llm_usage_summary": llm_usage_summary,
            "calendar": {
                "today": str(today),
                "is_trading_day": self.calendar.is_trading_day(today),
                "next_trading_day": str(self.calendar.next_trading_day(today)),
            },
        }

    # -----------------------------------------------------------------------
    # Backward Compatibility Aliases (For Regression Tests)
    # -----------------------------------------------------------------------
    @property
    def _reconciliation_blocked(self) -> bool:
        """兼容旧属性: 返回对账阻断状态。"""
        return self.recon_guard.blocked

    @_reconciliation_blocked.setter
    def _reconciliation_blocked(self, value: bool) -> None:
        """兼容旧属性: 设置对账阻断状态。"""
        if value:
            self.recon_guard.block(reason="legacy_set", operator="test")
        else:
            self.recon_guard.unblock(reason="legacy_set", operator="test")

    @property
    def _reconciliation_block_reason(self) -> dict[str, Any]:
        """兼容旧属性。"""
        return self.recon_guard.block_reason

    @_reconciliation_block_reason.setter
    def _reconciliation_block_reason(self, value: dict[str, Any]) -> None:
        self.recon_guard.block_reason = value

    @property
    def _reconciliation_ok_streak(self) -> int:
        return self.recon_guard.ok_streak

    @_reconciliation_ok_streak.setter
    def _reconciliation_ok_streak(self, value: int) -> None:
        self.recon_guard.ok_streak = value

    @property
    def _auto_unblock_enabled(self) -> bool:
        return self.recon_guard.auto_unblock_enabled

    @_auto_unblock_enabled.setter
    def _auto_unblock_enabled(self, value: bool) -> None:
        self.recon_guard.auto_unblock_enabled = value

    @property
    def _auto_unblock_required_ok_streak(self) -> int:
        return self.recon_guard.auto_unblock_required_ok_streak

    @_auto_unblock_required_ok_streak.setter
    def _auto_unblock_required_ok_streak(self, value: int) -> None:
        self.recon_guard.auto_unblock_required_ok_streak = value

    def get_budget_recovery_guard_state(self) -> dict[str, Any]:
        """兼容旧 API: 返回 BudgetRecoveryGuard 的状态。"""
        state = self.budget_guard.get_status()
        # Add missing metrics for backward compatibility
        metrics = state.get("metrics", {})
        metrics.setdefault("auto_recovery_success_count", 0)
        state["metrics"] = metrics
        return state

    def get_reconciliation_guard_state(self) -> dict[str, Any]:
        """兼容旧 API: 返回 ReconciliationGuard 的状态。"""
        return self.recon_guard.get_status()

    def _apply_reconciliation_guard(self, report: dict[str, Any]) -> None:
        """兼容旧 API: 委托给 ReconciliationGuard 处理结果。"""
        self.recon_guard.handle_reconciliation_result(report)
        # Sync test-set attributes back to guard in case they were modified
        if hasattr(self, '__test_recon_blocked_set'):
            pass


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _is_env_true(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _parse_csv_set(raw: str) -> set[str]:
    values: set[str] = set()
    for item in str(raw or "").split(","):
        text = item.strip().upper()
        if text:
            values.add(text)
    return values


class _FallbackVM:
    """无外部依赖时的降级 VM，保证系统可启动与可调试。"""

    async def run(self, ticker: str, initial_context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return {
            "session_id": "fallback-session",
            "ticker": ticker,
            "messages": [],
            "current_agent": "fallback",
            "decision": "HOLD",
            "confidence": 0.0,
            "analysis_reports": {},
            "context": initial_context or {},
            "trading_decision": {
                "action": "HOLD",
                "percentage": 0,
                "reason": "TradingVM 不可用，已降级",
                "confidence": 0,
            },
        }
