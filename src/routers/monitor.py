# -*- coding: utf-8 -*-
"""监控与风控 API 路由。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from src.core.errors import TradingServiceError, error_response, ok_response
from src.services.monitor_service import MonitorService

router = APIRouter()


def _get_service(request: Request):
    service = getattr(request.app.state, "trading_service", None)
    if not service:
        raise TradingServiceError(code="SERVICE_NOT_READY", message="TradingService not ready", http_status=503)
    return service


def _get_monitor_service(request: Request) -> MonitorService:
    return MonitorService(_get_service(request))


def _get_monitor_switches(request: Request) -> dict[str, bool]:
    state = getattr(request.app.state, "monitor_risk_switches", None)
    if isinstance(state, dict):
        return state
    defaults = {
        "auto_stop": True,
        "blacklist": True,
        "deviation": False,
    }
    request.app.state.monitor_risk_switches = defaults
    return defaults


def _error_json(exc: TradingServiceError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.http_status,
        content=error_response(exc.code, exc.message, exc.details),
    )


@router.get("/status")
async def get_system_status(request: Request):
    """获取交易通道健康状态。"""
    try:
        payload = _get_monitor_service(request).get_system_status()
        return ok_response(payload)
    except TradingServiceError as exc:
        return _error_json(exc)


@router.get("/data-health")
async def get_data_health(request: Request):
    """获取 AkShare/BaoStock 数据健康状态。"""
    try:
        payload = _get_monitor_service(request).get_data_health()
        return ok_response(payload)
    except TradingServiceError as exc:
        return _error_json(exc)


@router.get("/risk")
async def get_risk_metrics(request: Request):
    """读取实时风控指标。"""
    try:
        switches = _get_monitor_switches(request)
        payload = _get_monitor_service(request).get_risk_metrics(switches=switches)
        return ok_response(payload)
    except TradingServiceError as exc:
        return _error_json(exc)


@router.get("/audit")
async def get_audit_logs(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """读取审计日志。"""
    try:
        _get_service(request)
        payload = _get_monitor_service(request).list_audit_logs(limit=limit, offset=offset)
        return ok_response(payload)
    except TradingServiceError as exc:
        return _error_json(exc)


@router.post("/risk/toggle")
async def toggle_risk_switch(request: Request, body: dict[str, Any]):
    """更新风控开关状态。"""
    try:
        switch_name = str(body.get("name", "")).strip()
        enabled = bool(body.get("enabled", False))
        if not switch_name:
            raise TradingServiceError(code="INVALID_ORDER_REQUEST", message="name is required", http_status=400)

        switches = dict(_get_monitor_switches(request))
        payload = _get_monitor_service(request).toggle_risk_switch(
            switch_name=switch_name,
            enabled=enabled,
            switches=switches,
        )
        request.app.state.monitor_risk_switches = payload["switches"]
        return ok_response(payload)
    except TradingServiceError as exc:
        return _error_json(exc)


@router.get("/quote/{ticker}")
async def get_market_quote(request: Request, ticker: str):
    """获取实时行情。"""
    try:
        payload = await _get_monitor_service(request).get_market_quote(ticker)
        return ok_response(payload)
    except TradingServiceError as exc:
        return _error_json(exc)


@router.get("/kline/{ticker}")
async def get_market_kline(
    request: Request,
    ticker: str,
    interval: str = Query("daily"),
    limit: int = Query(100),
):
    """获取历史 K 线。"""
    _ = interval
    try:
        payload = await _get_monitor_service(request).get_market_kline(ticker, limit=limit)
        return ok_response(payload)
    except TradingServiceError as exc:
        return _error_json(exc)

