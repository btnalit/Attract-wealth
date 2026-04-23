from __future__ import annotations

import os

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from src.core.schemas import BaseSchema

from src.core.errors import TradingServiceError, error_response, ok_response
from src.core.trading_service import TradingService

router = APIRouter()


class TickerRequest(BaseSchema):
    ticker: str = Field(..., description="股票代码，例如 000001")


class BatchRequest(BaseModel):
    tickers: list[str] = Field(..., min_length=1, description="股票代码列表")
    execute_orders: bool = Field(default=True, description="是否执行下单，false 时仅分析")
    max_concurrency: int = Field(default=5, ge=1, le=20, description="最大并发")


class ReconcileRequest(BaseModel):
    initial_cash: float | None = Field(default=None, description="可选，对账初始现金基准")


class ReconcileUnlockRequest(BaseSchema):
    reason: str = Field(default="manual_api", description="手动解除阻断原因")
    operator: str = Field(default="api", description="触发方")


class DayRollRequest(BaseModel):
    reason: str = Field(default="manual", description="日切触发原因")
    force: bool = Field(default=False, description="是否强制在非交易日执行")


class CancelAllOrdersRequest(BaseSchema):
    reason: str = Field(default="manual", description="批量撤单原因")


class ChannelSwitchRequest(BaseSchema):
    channel: str = Field(..., description="目标交易通道：simulation/ths_auto/ths_ipc/qmt")
    reconnect: bool = Field(default=True, description="切换后是否立即尝试连接新通道")


class DirectOrderRequest(BaseSchema):
    ticker: str = Field(..., description="股票代码，例如 000001")
    side: str = Field(..., description="BUY 或 SELL")
    quantity: int | None = Field(default=None, ge=1, description="委托数量")
    qty: int | None = Field(default=None, ge=1, description="委托数量（兼容字段）")
    price: float = Field(..., gt=0, description="委托价格")
    order_type: str = Field(default="", description="limit 或 market")
    type: str = Field(default="", description="limit 或 market（兼容字段）")
    idempotency_key: str = Field(..., description="幂等键")
    client_order_id: str = Field(default="", description="外部系统订单号")
    channel: str = Field(default="", description="交易通道，默认使用当前服务通道")
    memo: str = Field(default="", description="备注")
    request_id: str = Field(default="", description="外部请求 ID（可选）")
    trace_id: str = Field(default="", description="全链路追踪 ID（可选）")
    manual_confirm: bool = Field(default=False, description="人工确认标记")
    manual_confirm_token: str = Field(default="", description="人工确认 token（可选）")


def _get_service(request: Request) -> TradingService:
    service = getattr(request.app.state, "trading_service", None)
    if service is None:
        raise TradingServiceError(
            code="SERVICE_NOT_READY",
            message="trading_service 未初始化",
            http_status=503,
        )
    return service


def _error_json(exc: TradingServiceError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.http_status,
        content=error_response(exc.code, exc.message, exc.details),
    )


@router.post("/analyze")
async def analyze(req: TickerRequest, request: Request):
    try:
        service = _get_service(request)
        result = await service.analyze(req.ticker)
        return ok_response(result, code="ANALYZE_OK")
    except TradingServiceError as exc:
        return _error_json(exc)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=error_response("INTERNAL_ERROR", "分析任务失败", {"error": str(exc)}),
        )


@router.post("/execute")
async def execute(req: TickerRequest, request: Request):
    try:
        service = _get_service(request)
        result = await service.execute(req.ticker)
        if result.get("risk_check", {}).get("passed") is False:
            return JSONResponse(
                status_code=409,
                content=error_response("RISK_REJECTED", "风控拒绝下单", result.get("risk_check", {})),
            )
        return ok_response(result, code="EXECUTE_OK")
    except TradingServiceError as exc:
        return _error_json(exc)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=error_response("INTERNAL_ERROR", "执行任务失败", {"error": str(exc)}),
        )


@router.post("/batch")
async def batch(req: BatchRequest, request: Request):
    try:
        service = _get_service(request)
        result = await service.run_batch(
            tickers=req.tickers,
            max_concurrency=req.max_concurrency,
            execute_orders=req.execute_orders,
        )
        return ok_response(result, code="BATCH_OK")
    except TradingServiceError as exc:
        return _error_json(exc)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=error_response("INTERNAL_ERROR", "批量任务失败", {"error": str(exc)}),
        )


@router.get("/positions")
async def positions(request: Request):
    try:
        service = _get_service(request)
        return ok_response(await service.get_positions(), code="POSITIONS_OK")
    except TradingServiceError as exc:
        return _error_json(exc)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=error_response("INTERNAL_ERROR", "查询持仓失败", {"error": str(exc)}),
        )


@router.get("/balance")
async def balance(request: Request):
    try:
        service = _get_service(request)
        return ok_response(await service.get_balance(), code="BALANCE_OK")
    except TradingServiceError as exc:
        return _error_json(exc)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=error_response("INTERNAL_ERROR", "查询账户失败", {"error": str(exc)}),
        )


@router.get("/orders/active")
async def active_orders(request: Request):
    try:
        service = _get_service(request)
        return ok_response(await service.get_active_orders(), code="ACTIVE_ORDERS_OK")
    except TradingServiceError as exc:
        return _error_json(exc)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=error_response("INTERNAL_ERROR", "查询活动订单失败", {"error": str(exc)}),
        )


@router.get("/snapshot")
async def trade_snapshot(
    request: Request,
    include_channel_raw: bool = Query(default=True, description="是否包含通道原始快照"),
):
    try:
        service = _get_service(request)
        payload = await service.get_trade_snapshot(include_channel_raw=include_channel_raw)
        return ok_response(payload, code="SNAPSHOT_OK")
    except TradingServiceError as exc:
        return _error_json(exc)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=error_response("INTERNAL_ERROR", "查询交易快照失败", {"error": str(exc)}),
        )


@router.post("/orders/sync")
async def sync_orders(request: Request):
    try:
        service = _get_service(request)
        return ok_response(await service.sync_orders_now(), code="ORDERS_SYNC_OK")
    except TradingServiceError as exc:
        return _error_json(exc)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=error_response("INTERNAL_ERROR", "订单同步失败", {"error": str(exc)}),
        )


@router.post("/orders/cancel-all")
async def cancel_all_orders(req: CancelAllOrdersRequest, request: Request):
    """批量撤销当前活动订单。"""
    try:
        service = _get_service(request)
        payload = await service.cancel_active_orders(reason=req.reason)
        return ok_response(payload, code="ORDERS_CANCEL_ALL_OK")
    except TradingServiceError as exc:
        return _error_json(exc)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=error_response("INTERNAL_ERROR", "批量撤单失败", {"error": str(exc)}),
        )


@router.post("/channel/switch")
async def switch_trading_channel(req: ChannelSwitchRequest, request: Request):
    """切换交易通道并重建执行上下文。"""
    try:
        service = _get_service(request)
        payload = await service.switch_channel(target_channel=req.channel, reconnect=bool(req.reconnect))
        return ok_response(payload, code="TRADING_CHANNEL_SWITCHED")
    except TradingServiceError as exc:
        return _error_json(exc)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=error_response("INTERNAL_ERROR", "切换交易通道失败", {"error": str(exc)}),
        )


@router.post("/orders/direct")
async def direct_order(req: DirectOrderRequest, request: Request):
    try:
        service = _get_service(request)
        request_id = req.request_id.strip() or request.headers.get("X-Request-ID", "").strip()
        trace_id = req.trace_id.strip() or request.headers.get("X-Trace-ID", "").strip() or request_id
        manual_confirm_token = (
            req.manual_confirm_token.strip() or request.headers.get("X-Manual-Confirm-Token", "").strip()
        )
        manual_confirm_header = request.headers.get("X-Manual-Confirm", "").strip().lower()
        manual_confirm = req.manual_confirm or manual_confirm_header in {"1", "true", "yes", "on"}
        quantity = req.quantity if req.quantity is not None else req.qty
        if quantity is None:
            raise TradingServiceError(
                code="INVALID_ORDER_REQUEST",
                message="quantity/qty is required",
                http_status=400,
            )
        if req.quantity is not None and req.qty is not None and int(req.quantity) != int(req.qty):
            raise TradingServiceError(
                code="INVALID_ORDER_REQUEST",
                message="quantity and qty mismatch",
                details={"quantity": req.quantity, "qty": req.qty},
                http_status=400,
            )

        order_type = req.order_type.strip() or req.type.strip() or "limit"
        if req.order_type.strip() and req.type.strip() and req.order_type.strip().lower() != req.type.strip().lower():
            raise TradingServiceError(
                code="INVALID_ORDER_REQUEST",
                message="order_type and type mismatch",
                details={"order_type": req.order_type, "type": req.type},
                http_status=400,
            )

        result = await service.place_direct_order(
            ticker=req.ticker,
            side=req.side,
            quantity=int(quantity),
            price=req.price,
            order_type=order_type,
            idempotency_key=req.idempotency_key,
            client_order_id=req.client_order_id,
            request_id=request_id,
            channel=req.channel,
            memo=req.memo,
            manual_confirm=manual_confirm,
            manual_confirm_token=manual_confirm_token,
            trace_id=trace_id,
        )
        if result.get("risk_check", {}).get("passed") is False:
            return JSONResponse(
                status_code=409,
                content=error_response("RISK_REJECTED", "风控拒绝下单", result),
            )

        order_status = str((result.get("order") or {}).get("status", "")).lower()
        if order_status == "rejected":
            return JSONResponse(
                status_code=409,
                content=error_response("ORDER_REJECTED", "通道拒单", result),
            )
        if order_status == "failed":
            return JSONResponse(
                status_code=502,
                content=error_response("ORDER_FAILED", "通道下单失败", result),
            )

        code = "DIRECT_ORDER_REPLAY" if result.get("idempotent_replay", False) else "DIRECT_ORDER_ACCEPTED"
        return ok_response(result, code=code)
    except TradingServiceError as exc:
        return _error_json(exc)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=error_response("INTERNAL_ERROR", "直下单任务失败", {"error": str(exc)}),
        )


@router.get("/orders/trace")
async def order_trace(
    request: Request,
    idempotency_key: str = Query(default=""),
    local_order_id: str = Query(default=""),
    client_order_id: str = Query(default=""),
    request_id: str = Query(default=""),
    trace_id: str = Query(default=""),
):
    try:
        if not any(
            [idempotency_key.strip(), local_order_id.strip(), client_order_id.strip(), request_id.strip(), trace_id.strip()]
        ):
            raise TradingServiceError(
                code="INVALID_ORDER_REQUEST",
                message="至少提供一个查询条件：idempotency_key/local_order_id/client_order_id/request_id/trace_id",
                http_status=400,
            )
        service = _get_service(request)
        trace = service.get_direct_order_trace(
            idempotency_key=idempotency_key,
            local_order_id=local_order_id,
            client_order_id=client_order_id,
            request_id=request_id,
            trace_id=trace_id,
        )
        if not trace:
            raise TradingServiceError(
                code="ORDER_TRACE_NOT_FOUND",
                message="未找到订单追踪记录",
                details={
                    "idempotency_key": idempotency_key,
                    "local_order_id": local_order_id,
                    "client_order_id": client_order_id,
                    "request_id": request_id,
                    "trace_id": trace_id,
                },
                http_status=404,
            )
        return ok_response(trace, code="ORDER_TRACE_OK")
    except TradingServiceError as exc:
        return _error_json(exc)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=error_response("INTERNAL_ERROR", "订单追踪查询失败", {"error": str(exc)}),
        )


@router.post("/reconcile")
async def reconcile(req: ReconcileRequest, request: Request):
    try:
        service = _get_service(request)
        report = await service.reconcile(initial_cash=req.initial_cash)
        if report.get("action") == "block":
            return JSONResponse(
                status_code=409,
                content=error_response("RECON_BLOCK", "对账触发阻断", report),
            )
        if report.get("status") == "mismatch":
            return JSONResponse(
                status_code=200,
                content=ok_response(report, code="RECON_WARN"),
            )
        return ok_response(report, code="RECON_OK")
    except TradingServiceError as exc:
        return _error_json(exc)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=error_response("INTERNAL_ERROR", "对账任务失败", {"error": str(exc)}),
        )


@router.post("/reconcile/unlock")
async def reconcile_unlock(req: ReconcileUnlockRequest, request: Request):
    try:
        service = _get_service(request)
        required_token = os.getenv("RECON_UNLOCK_TOKEN", "").strip()
        provided_token = request.headers.get("X-Recon-Unlock-Token", "").strip()
        if required_token and provided_token != required_token:
            raise TradingServiceError(
                code="UNAUTHORIZED_UNLOCK",
                message="未授权的解锁请求",
                details={"header": "X-Recon-Unlock-Token"},
                http_status=403,
            )

        source_ip = request.client.host if request.client else ""
        user_agent = request.headers.get("User-Agent", "")
        result = service.unlock_reconciliation_block(
            reason=req.reason,
            operator=req.operator,
            source_ip=source_ip,
            user_agent=user_agent,
        )
        code = "RECON_UNLOCKED" if result.get("was_blocked") else "RECON_UNLOCK_NOOP"
        return ok_response(result, code=code)
    except TradingServiceError as exc:
        return _error_json(exc)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=error_response("INTERNAL_ERROR", "手动解除阻断失败", {"error": str(exc)}),
        )


@router.post("/day-roll")
async def day_roll(req: DayRollRequest, request: Request):
    try:
        service = _get_service(request)
        result = await service.day_roll(reason=req.reason, force=req.force)
        if result.get("skipped"):
            return JSONResponse(
                status_code=200,
                content=ok_response(result, code="NON_TRADING_DAY_SKIP"),
            )
        recon = result.get("reconciliation", {})
        if recon.get("action") == "block":
            return JSONResponse(
                status_code=409,
                content=error_response("DAY_ROLL_RECON_BLOCK", "日切完成但对账触发阻断", result),
            )
        return ok_response(result, code="DAY_ROLL_OK")
    except TradingServiceError as exc:
        return _error_json(exc)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=error_response("INTERNAL_ERROR", "日切任务失败", {"error": str(exc)}),
        )


