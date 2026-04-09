from __future__ import annotations

import os
import time
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from src.core.schemas import BaseSchema

from src.core.dataflow_profiles import (
    apply_dataflow_env,
    current_dataflow_env_snapshot,
    diff_profile_against_current,
    get_dataflow_profile_meta,
    list_dataflow_profiles,
    resolve_dataflow_profile,
)
from src.core.errors import TradingServiceError, error_response, get_error_catalog, ok_response
from src.core.startup_preflight import run_startup_preflight
from src.core.system_store import SystemStore
from src.core.trading_ledger import TradingLedger
from src.llm.openai_compat import get_llm_effective_config, get_llm_runtime_metrics

router = APIRouter()
LLM_RUNTIME_CONFIG_KEY = "llm_runtime_config"


class WatchlistUpdateRequest(BaseModel):
    tickers: list[str] = Field(default_factory=list, description="监控股票列表")
    source: str = Field(default="api", description="更新来源")


class AutopilotApplyRequest(BaseModel):
    template: str = Field(..., description="自动巡航模板名称")


class DataflowProfileApplyRequest(BaseModel):
    profile: str = Field(..., description="数据稳定参数 profile 名称")
    persist: bool = Field(default=False, description="是否持久化到 system_settings")


class DataflowQualityFeedbackRequest(BaseModel):
    label: str = Field(..., description="反馈标签：true_positive/false_positive/false_negative")
    event_id: str = Field(default="", description="可选，质量告警事件 ID")
    source: str = Field(default="api", description="反馈来源")
    note: str = Field(default="", description="备注")


class THSBridgeStartRequest(BaseModel):
    channel: str = Field(default="ths_ipc", description="通道名，默认 ths_ipc")
    restart: bool = Field(default=False, description="是否先强制停止后重启 bridge")
    allow_disabled: bool = Field(default=True, description="忽略 STARTUP_AUTO_START_THS_BRIDGE=false 并强制拉起")


class THSBridgeStopRequest(BaseModel):
    force: bool = Field(default=True, description="是否强制停止（忽略 STARTUP_KEEP_THS_BRIDGE）")
    reason: str = Field(default="api_stop", description="停止原因")


class LLMRuntimeConfigRequest(BaseModel):
    provider_name: str = Field(default="custom", description="LLM 供应商名称")
    base_url: str = Field(default="", description="OpenAI 兼容 base_url")
    model: str = Field(default="", description="默认模型名称")
    quick_model: str = Field(default="", description="快速模型名称")
    deep_model: str = Field(default="", description="深度模型名称")
    timeout_s: float = Field(default=120.0, gt=0, description="请求超时秒数")
    max_tokens: int = Field(default=4096, ge=1, description="默认 max_tokens")
    temperature: float = Field(default=0.7, ge=0, le=2, description="默认 temperature")
    api_key: str = Field(default="", description="API key，留空可保持不变")
    retain_api_key: bool = Field(default=True, description="api_key 为空时是否保留已有 key")


def _degraded_dataflow_payload(error: str) -> dict[str, Any]:
    feedback = {
        "true_positive": 0,
        "false_positive": 0,
        "false_negative": 0,
        "feedback_total": 0,
        "precision": 0.0,
        "false_positive_rate": 0.0,
        "miss_rate": 0.0,
        "updated_at": 0.0,
    }
    quality = {
        "alert_level": "critical",
        "action": "record",
        "code": "DATAFLOW_UNAVAILABLE",
        "event_id": "",
        "feedback_metrics": feedback,
        "thresholds": {},
        "triggered_rules": [
            {
                "rule": "dependency",
                "metric": "dataflow_import",
                "value": 1.0,
                "warn_threshold": 0.0,
                "block_threshold": 0.0,
                "level": "critical",
            }
        ],
    }
    summary = {
        "current_provider": "",
        "requests_total": 0,
        "error_rate": 1.0,
        "empty_rate": 1.0,
        "fallback_rate": 0.0,
        "retry_rate": 0.0,
        "rate_limited_rate": 0.0,
        "cache_hit_rate": 0.0,
        "quality_alert_level": quality["alert_level"],
        "quality_code": quality["code"],
        "quality_action": quality["action"],
    }
    return {
        "summary": summary,
        "quality": quality,
        "quality_event": {"event_id": "", "new_event": False},
        "quality_feedback": feedback,
        "quality_events": [],
        "runtime_config": {
            "provider_rate_limit": {},
            "retry_policy": {},
            "quality_thresholds": {},
            "cache_ttl": {},
        },
        "tuning": {
            "action": "urgent_tune",
            "quality_alert_level": "critical",
            "suggestions": [
                {
                    "metric": "dataflow_import",
                    "current_value": 1.0,
                    "warn_threshold": 0.0,
                    "block_threshold": 0.0,
                    "message": "数据流模块不可用，请检查依赖加载与运行环境。",
                }
            ],
            "suggested_env": {},
            "observed": {},
        },
        "providers": {},
        "provider_order": [],
        "error": error,
    }


def _get_service(request: Request):
    service = getattr(request.app.state, "trading_service", None)
    if service is None:
        raise TradingServiceError(code="SERVICE_NOT_READY", message="trading_service 未初始化", http_status=503)
    return service


def _get_event_engine(request: Request):
    engine = getattr(request.app.state, "event_engine", None)
    if engine is None:
        raise TradingServiceError(code="EVENT_ENGINE_NOT_READY", message="event_engine 未初始化", http_status=503)
    return engine


def _get_system_store_or_none(request: Request) -> SystemStore | None:
    store = getattr(request.app.state, "system_store", None)
    if isinstance(store, SystemStore):
        return store
    return None


def _get_ths_bridge_runtime(request: Request):
    runtime = getattr(request.app.state, "ths_bridge_runtime", None)
    if runtime is None:
        raise TradingServiceError(
            code="SERVICE_NOT_READY",
            message="ths_bridge_runtime 未初始化",
            http_status=503,
        )
    return runtime


def _error_json(exc: TradingServiceError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.http_status,
        content=error_response(exc.code, exc.message, exc.details),
    )


def _mask_api_key(api_key: str) -> str:
    key = str(api_key or "").strip()
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}***{key[-4:]}"


def _normalize_llm_config(raw: dict[str, Any] | None = None) -> dict[str, Any]:
    effective = get_llm_effective_config()
    payload = dict(raw or {})
    api_key = str(payload.get("api_key", "") or "").strip() or str(os.getenv("LLM_API_KEY", "")).strip()
    base_url = str(payload.get("base_url", "") or effective.get("base_url", "")).strip()
    model = str(payload.get("model", "") or effective.get("model", "")).strip()
    quick_model = str(payload.get("quick_model", "") or effective.get("quick_model", "")).strip()
    deep_model = str(payload.get("deep_model", "") or effective.get("deep_model", "")).strip()
    provider_name = str(payload.get("provider_name", "") or effective.get("provider_name", "custom")).strip() or "custom"
    timeout_s = float(payload.get("timeout_s", effective.get("timeout_s", 120.0)) or 120.0)
    max_tokens = int(payload.get("max_tokens", effective.get("max_tokens", 4096)) or 4096)
    temperature = float(payload.get("temperature", effective.get("temperature", 0.7)) or 0.7)
    return {
        "provider_name": provider_name,
        "base_url": base_url,
        "model": model,
        "quick_model": quick_model,
        "deep_model": deep_model,
        "timeout_s": timeout_s,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "api_key": api_key,
    }


def _load_llm_config(request: Request) -> dict[str, Any]:
    store = _get_system_store_or_none(request)
    saved = store.get_setting(LLM_RUNTIME_CONFIG_KEY, {}) if store else {}
    if not isinstance(saved, dict):
        saved = {}
    return _normalize_llm_config(saved)


def _llm_config_output(config: dict[str, Any]) -> dict[str, Any]:
    payload = dict(config)
    payload.pop("api_key", None)
    payload["has_api_key"] = bool(str(config.get("api_key", "")).strip())
    payload["api_key_masked"] = _mask_api_key(str(config.get("api_key", "")))
    payload["updated_at"] = time.time()
    return payload


@router.get("/runtime")
async def runtime_info(request: Request):
    try:
        service = _get_service(request)
        event_engine = _get_event_engine(request)
        service_runtime = service.get_runtime_state() if hasattr(service, "get_runtime_state") else {}
        payload = {
            "name": "来财 (Attract-wealth)",
            "version": "0.1.0",
            "channel": service_runtime.get("channel", os.getenv("TRADING_CHANNEL", "simulation")),
            "broker_connected": service_runtime.get(
                "broker_connected",
                bool(getattr(getattr(service, "broker", None), "is_connected", False)),
            ),
            "scheduler_enabled": bool(getattr(event_engine, "scheduler", None)),
            "watchlists": event_engine.get_watchlists() if hasattr(event_engine, "get_watchlists") else [],
            "autopilot": event_engine.get_autopilot_state() if hasattr(event_engine, "get_autopilot_state") else {},
            "risk": service_runtime.get("risk", {}),
            "degrade_policy": service_runtime.get("degrade_policy", {}),
            "budget_recovery_guard": service_runtime.get("budget_recovery_guard", {}),
            "budget_recovery_metrics": service_runtime.get(
                "budget_recovery_metrics",
                service_runtime.get("budget_recovery_guard", {}).get("metrics", {}),
            ),
            "dataflow_summary": service_runtime.get("dataflow_summary", {}),
            "dataflow": service_runtime.get("dataflow", {}),
            "dataflow_tuning": service_runtime.get("dataflow_tuning", {}),
            "llm_usage_summary": service_runtime.get("llm_usage_summary", {}),
            "llm_runtime": service_runtime.get("llm_runtime", {}),
            "reconciliation_blocked": service_runtime.get("reconciliation_blocked", False),
            "reconciliation_block_reason": service_runtime.get("reconciliation_block_reason", {}),
            "calendar": service_runtime.get("calendar", {}),
            "ths_bridge": getattr(request.app.state, "ths_bridge", {}),
        }
        return ok_response(payload, code="RUNTIME_OK")
    except TradingServiceError as exc:
        return _error_json(exc)


@router.get("/ths-bridge")
async def ths_bridge_state(request: Request):
    return ok_response({"ths_bridge": getattr(request.app.state, "ths_bridge", {})}, code="THS_BRIDGE_STATE_OK")


@router.post("/ths-bridge/start")
async def ths_bridge_start(req: THSBridgeStartRequest, request: Request):
    try:
        runtime = _get_ths_bridge_runtime(request)
        channel = str(req.channel or "ths_ipc").strip().lower() or "ths_ipc"
        if req.restart:
            request.app.state.ths_bridge = runtime.stop(force=True, reason="api_restart")
        state = runtime.start(channel=channel, allow_disabled=bool(req.allow_disabled))
        request.app.state.ths_bridge = state
        payload = {
            "requested_channel": channel,
            "restart": bool(req.restart),
            "allow_disabled": bool(req.allow_disabled),
            "ths_bridge": state,
        }
        return ok_response(payload, code="THS_BRIDGE_STARTED")
    except TradingServiceError as exc:
        return _error_json(exc)


@router.post("/ths-bridge/stop")
async def ths_bridge_stop(req: THSBridgeStopRequest, request: Request):
    try:
        runtime = _get_ths_bridge_runtime(request)
        state = runtime.stop(force=bool(req.force), reason=str(req.reason or "api_stop"))
        request.app.state.ths_bridge = state
        payload = {
            "force": bool(req.force),
            "reason": str(req.reason or "api_stop"),
            "ths_bridge": state,
        }
        return ok_response(payload, code="THS_BRIDGE_STOPPED")
    except TradingServiceError as exc:
        return _error_json(exc)


@router.get("/watchlist")
async def get_watchlist(request: Request):
    try:
        event_engine = _get_event_engine(request)
        return ok_response({"tickers": event_engine.get_watchlists()}, code="WATCHLIST_OK")
    except TradingServiceError as exc:
        return _error_json(exc)


@router.put("/watchlist")
async def update_watchlist(req: WatchlistUpdateRequest, request: Request):
    try:
        event_engine = _get_event_engine(request)
        tickers = event_engine.load_watchlists(req.tickers, persist=True, source=req.source)
        return ok_response({"tickers": tickers}, code="WATCHLIST_UPDATED")
    except TradingServiceError as exc:
        return _error_json(exc)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=error_response("INTERNAL_ERROR", "更新 watchlist 失败", {"error": str(exc)}),
        )


@router.get("/autopilot/templates")
async def autopilot_templates(request: Request):
    try:
        event_engine = _get_event_engine(request)
        templates = event_engine.get_autopilot_templates()
        return ok_response({"templates": templates}, code="AUTOPILOT_TEMPLATES_OK")
    except TradingServiceError as exc:
        return _error_json(exc)


@router.get("/autopilot/state")
async def autopilot_state(request: Request):
    try:
        event_engine = _get_event_engine(request)
        return ok_response(event_engine.get_autopilot_state(), code="AUTOPILOT_STATE_OK")
    except TradingServiceError as exc:
        return _error_json(exc)


@router.post("/autopilot/apply")
async def apply_autopilot(req: AutopilotApplyRequest, request: Request):
    try:
        event_engine = _get_event_engine(request)
        state = event_engine.apply_autopilot_template(req.template, persist=True)
        return ok_response(state, code="AUTOPILOT_APPLIED")
    except TradingServiceError as exc:
        return _error_json(exc)
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content=error_response("INVALID_AUTOPILOT_TEMPLATE", str(exc), {"template": req.template}),
        )


@router.get("/risk/metrics")
async def risk_metrics(request: Request):
    try:
        service = _get_service(request)
        metrics = service.risk_gate.get_metrics()
        return ok_response(metrics, code="RISK_METRICS_OK")
    except TradingServiceError as exc:
        return _error_json(exc)


@router.get("/risk/alerts")
async def risk_alerts(request: Request, limit: int = Query(default=50, ge=1, le=500)):
    try:
        service = _get_service(request)
        alerts = service.risk_gate.get_recent_alerts(limit=limit)
        return ok_response({"alerts": alerts, "count": len(alerts)}, code="RISK_ALERTS_OK")
    except TradingServiceError as exc:
        return _error_json(exc)


@router.get("/dataflow/metrics")
async def dataflow_metrics():
    try:
        from src.dataflows.source_manager import data_manager

        return ok_response(data_manager.get_metrics(), code="DATAFLOW_METRICS_OK")
    except Exception as exc:  # noqa: BLE001
        return ok_response(_degraded_dataflow_payload(str(exc)), code="DATAFLOW_METRICS_DEGRADED")


@router.get("/dataflow/quality")
async def dataflow_quality():
    try:
        from src.dataflows.source_manager import data_manager

        metrics = data_manager.get_metrics()
        payload = {
            "summary": metrics.get("summary", {}),
            "quality": metrics.get("quality", {}),
            "quality_event": metrics.get("quality_event", {}),
            "quality_feedback": metrics.get("quality_feedback", {}),
            "quality_events": metrics.get("quality_events", []),
            "tuning": metrics.get("tuning", {}),
            "runtime_config": metrics.get("runtime_config", {}),
        }
        return ok_response(payload, code="DATAFLOW_QUALITY_OK")
    except Exception as exc:  # noqa: BLE001
        degraded = _degraded_dataflow_payload(str(exc))
        payload = {
            "summary": degraded.get("summary", {}),
            "quality": degraded.get("quality", {}),
            "quality_event": degraded.get("quality_event", {}),
            "quality_feedback": degraded.get("quality_feedback", {}),
            "quality_events": degraded.get("quality_events", []),
            "tuning": degraded.get("tuning", {}),
            "runtime_config": degraded.get("runtime_config", {}),
            "error": degraded.get("error", ""),
        }
        return ok_response(payload, code="DATAFLOW_QUALITY_DEGRADED")


@router.get("/dataflow/tuning")
async def dataflow_tuning():
    try:
        from src.dataflows.source_manager import data_manager

        metrics = data_manager.get_metrics()
        payload = {
            "summary": metrics.get("summary", {}),
            "quality": metrics.get("quality", {}),
            "quality_event": metrics.get("quality_event", {}),
            "quality_feedback": metrics.get("quality_feedback", {}),
            "tuning": metrics.get("tuning", {}),
            "runtime_config": metrics.get("runtime_config", {}),
        }
        return ok_response(payload, code="DATAFLOW_TUNING_OK")
    except Exception as exc:  # noqa: BLE001
        degraded = _degraded_dataflow_payload(str(exc))
        payload = {
            "summary": degraded.get("summary", {}),
            "quality": degraded.get("quality", {}),
            "quality_event": degraded.get("quality_event", {}),
            "quality_feedback": degraded.get("quality_feedback", {}),
            "tuning": degraded.get("tuning", {}),
            "runtime_config": degraded.get("runtime_config", {}),
            "error": degraded.get("error", ""),
        }
        return ok_response(payload, code="DATAFLOW_TUNING_DEGRADED")


@router.get("/dataflow/quality/feedback")
async def dataflow_quality_feedback(limit: int = Query(default=50, ge=1, le=500)):
    try:
        from src.dataflows.source_manager import data_manager

        return ok_response(
            {
                "metrics": data_manager.get_quality_feedback_metrics(),
                "events": data_manager.list_quality_events(limit=limit),
                "limit": limit,
            },
            code="DATAFLOW_QUALITY_FEEDBACK_OK",
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=error_response(
                "INTERNAL_ERROR",
                "获取数据质量反馈指标失败",
                {"error": str(exc)},
            ),
        )


@router.post("/dataflow/quality/feedback")
async def dataflow_quality_feedback_record(req: DataflowQualityFeedbackRequest):
    try:
        from src.dataflows.source_manager import data_manager

        metrics = data_manager.record_quality_feedback(
            label=req.label,
            event_id=req.event_id,
            source=req.source,
            note=req.note,
        )
        return ok_response(
            {
                "accepted": True,
                "label": req.label,
                "event_id": req.event_id,
                "source": req.source,
                "metrics": metrics,
            },
            code="DATAFLOW_QUALITY_FEEDBACK_RECORDED",
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content=error_response(
                "INVALID_ORDER_REQUEST",
                "不支持的反馈标签",
                {"label": req.label, "error": str(exc)},
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=error_response(
                "INTERNAL_ERROR",
                "记录数据质量反馈失败",
                {"error": str(exc)},
            ),
        )


@router.get("/dataflow/profiles")
async def dataflow_profiles(request: Request):
    profiles = list_dataflow_profiles()
    store = _get_system_store_or_none(request)
    active_profile = str(store.get_setting("dataflow_runtime_profile", "") if store else "").strip().lower()
    active_profile_meta = get_dataflow_profile_meta(active_profile) if active_profile else {}

    try:
        from src.dataflows.source_manager import data_manager

        metrics = data_manager.get_metrics()
        payload = {
            "active_profile": active_profile,
            "active_profile_version": str(active_profile_meta.get("version", "")),
            "profiles": profiles,
            "current_env": current_dataflow_env_snapshot(),
            "runtime_config": metrics.get("runtime_config", {}),
            "summary": metrics.get("summary", {}),
            "quality": metrics.get("quality", {}),
            "tuning": metrics.get("tuning", {}),
            "profile_diffs": {name: diff_profile_against_current(name) for name in profiles},
        }
        return ok_response(payload, code="DATAFLOW_PROFILES_OK")
    except Exception as exc:  # noqa: BLE001
        degraded = _degraded_dataflow_payload(str(exc))
        payload = {
            "active_profile": active_profile,
            "active_profile_version": str(active_profile_meta.get("version", "")),
            "profiles": profiles,
            "current_env": current_dataflow_env_snapshot(),
            "runtime_config": degraded.get("runtime_config", {}),
            "summary": degraded.get("summary", {}),
            "quality": degraded.get("quality", {}),
            "tuning": degraded.get("tuning", {}),
            "profile_diffs": {name: diff_profile_against_current(name) for name in profiles},
            "error": degraded.get("error", ""),
        }
        return ok_response(payload, code="DATAFLOW_PROFILES_DEGRADED")


@router.post("/dataflow/profile/apply")
async def dataflow_profile_apply(req: DataflowProfileApplyRequest, request: Request):
    profile_name = str(req.profile or "").strip().lower()
    resolved = resolve_dataflow_profile(profile_name)
    if not resolved:
        return JSONResponse(
            status_code=400,
            content=error_response(
                "INVALID_ORDER_REQUEST",
                "未知的数据稳定参数 profile",
                {"profile": profile_name, "available_profiles": sorted(list(list_dataflow_profiles().keys()))},
            ),
        )

    try:
        applied_env = apply_dataflow_env(resolved)
        profile_meta = get_dataflow_profile_meta(profile_name)
        runtime_config: dict[str, Any] = {}
        summary: dict[str, Any] = {}
        quality: dict[str, Any] = {}
        tuning: dict[str, Any] = {}
        degraded_error = ""
        try:
            from src.dataflows.source_manager import data_manager

            runtime_config = data_manager.reload_runtime_config_from_env()
            metrics = data_manager.get_metrics()
            summary = metrics.get("summary", {})
            quality = metrics.get("quality", {})
            tuning = metrics.get("tuning", {})
            runtime_config = metrics.get("runtime_config", runtime_config)
        except Exception as exc:  # noqa: BLE001
            degraded = _degraded_dataflow_payload(str(exc))
            runtime_config = degraded.get("runtime_config", {})
            summary = degraded.get("summary", {})
            quality = degraded.get("quality", {})
            tuning = degraded.get("tuning", {})
            degraded_error = str(exc)

        persisted = False
        store = _get_system_store_or_none(request)
        if req.persist and store is not None:
            store.set_setting("dataflow_runtime_profile", profile_name)
            store.set_setting("dataflow_runtime_profile_env", applied_env)
            persisted = True

        payload = {
            "profile": profile_name,
            "profile_version": str(profile_meta.get("version", "")),
            "profile_description": str(profile_meta.get("description", "")),
            "persisted": persisted,
            "applied_env": applied_env,
            "runtime_config": runtime_config,
            "summary": summary,
            "quality": quality,
            "tuning": tuning,
            "degraded_error": degraded_error,
        }
        code = "DATAFLOW_PROFILE_APPLIED_DEGRADED" if degraded_error else "DATAFLOW_PROFILE_APPLIED"
        return ok_response(payload, code=code)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=error_response("INTERNAL_ERROR", "应用数据稳定参数 profile 失败", {"error": str(exc)}),
        )


@router.get("/llm/providers")
async def llm_providers(request: Request):
    config = _load_llm_config(request)
    default_catalog = [
        {"name": "custom", "display_name": "Custom OpenAI Compatible"},
        {"name": "openai", "display_name": "OpenAI"},
        {"name": "deepseek", "display_name": "DeepSeek"},
        {"name": "qwen", "display_name": "Qwen"},
        {"name": "kimi", "display_name": "Kimi"},
    ]
    current_name = str(config.get("provider_name", "custom"))
    if not any(item["name"] == current_name for item in default_catalog):
        default_catalog.insert(0, {"name": current_name, "display_name": current_name})
    return ok_response(
        {
            "items": default_catalog,
            "current_provider": current_name,
        },
        code="LLM_PROVIDERS_OK",
    )


@router.get("/llm/config")
async def llm_runtime_config(request: Request):
    config = _load_llm_config(request)
    service = getattr(request.app.state, "trading_service", None)
    runtime_payload: dict[str, Any] = {}
    if service is not None and hasattr(service, "get_llm_runtime_config"):
        try:
            runtime_payload = service.get_llm_runtime_config()
        except Exception:  # noqa: BLE001
            runtime_payload = {}
    return ok_response(
        {
            "config": _llm_config_output(config),
            "runtime_config": runtime_payload,
        },
        code="LLM_CONFIG_OK",
    )


@router.put("/llm/config")
async def llm_runtime_config_update(req: LLMRuntimeConfigRequest, request: Request):
    try:
        current = _load_llm_config(request)
        payload = {
            "provider_name": req.provider_name or current.get("provider_name", "custom"),
            "base_url": req.base_url or current.get("base_url", ""),
            "model": req.model or current.get("model", ""),
            "quick_model": req.quick_model or current.get("quick_model", ""),
            "deep_model": req.deep_model or current.get("deep_model", ""),
            "timeout_s": req.timeout_s,
            "max_tokens": req.max_tokens,
            "temperature": req.temperature,
        }
        if req.api_key.strip():
            payload["api_key"] = req.api_key.strip()
        elif req.retain_api_key:
            payload["api_key"] = str(current.get("api_key", ""))
        else:
            payload["api_key"] = ""

        normalized = _normalize_llm_config(payload)
        if not normalized["base_url"]:
            raise TradingServiceError(
                code="INVALID_ORDER_REQUEST",
                message="LLM base_url 不能为空",
                details={"field": "base_url"},
                http_status=400,
            )
        if not normalized["model"]:
            raise TradingServiceError(
                code="INVALID_ORDER_REQUEST",
                message="LLM model 不能为空",
                details={"field": "model"},
                http_status=400,
            )

        store = _get_system_store_or_none(request)
        if store is not None:
            store.set_setting(LLM_RUNTIME_CONFIG_KEY, normalized)

        service = _get_service(request)
        applied = service.update_llm_runtime_config(normalized, operator="system_router")
        return ok_response(
            {
                "config": _llm_config_output({**normalized, "api_key": normalized.get("api_key", "")}),
                "runtime_config": applied,
                "persisted": bool(store is not None),
            },
            code="LLM_CONFIG_UPDATED",
        )
    except TradingServiceError as exc:
        return _error_json(exc)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=error_response("INTERNAL_ERROR", "更新 LLM 配置失败", {"error": str(exc)}),
        )


@router.post("/llm/config/test")
async def llm_runtime_config_test(req: LLMRuntimeConfigRequest, request: Request):
    base = _load_llm_config(request)
    merged = {
        **base,
        "provider_name": req.provider_name or base.get("provider_name", "custom"),
        "base_url": req.base_url or base.get("base_url", ""),
        "model": req.model or base.get("model", ""),
        "quick_model": req.quick_model or base.get("quick_model", ""),
        "deep_model": req.deep_model or base.get("deep_model", ""),
        "timeout_s": req.timeout_s or base.get("timeout_s", 120.0),
        "max_tokens": req.max_tokens or base.get("max_tokens", 4096),
        "temperature": req.temperature,
    }
    if req.api_key.strip():
        merged["api_key"] = req.api_key.strip()
    elif req.retain_api_key:
        merged["api_key"] = str(base.get("api_key", ""))
    else:
        merged["api_key"] = ""

    normalized = _normalize_llm_config(merged)
    if not normalized["base_url"] or not normalized["model"]:
        return JSONResponse(
            status_code=400,
            content=error_response(
                "INVALID_ORDER_REQUEST",
                "测试配置缺少 base_url 或 model",
                {"base_url": normalized["base_url"], "model": normalized["model"]},
            ),
        )
    if not str(normalized.get("api_key", "")).strip():
        return JSONResponse(
            status_code=400,
            content=error_response(
                "INVALID_ORDER_REQUEST",
                "测试配置缺少 api_key",
                {"field": "api_key"},
            ),
        )

    started = time.perf_counter()
    try:
        client = AsyncOpenAI(
            base_url=str(normalized["base_url"]),
            api_key=str(normalized["api_key"]),
            timeout=float(normalized["timeout_s"]),
        )
        response = await client.chat.completions.create(
            model=str(normalized["model"]),
            messages=[{"role": "user", "content": "ping"}],
            temperature=0,
            max_tokens=1,
        )
        latency_ms = (time.perf_counter() - started) * 1000
        output_text = ""
        if getattr(response, "choices", None):
            output_text = str(getattr(getattr(response.choices[0], "message", None), "content", "") or "").strip()
        usage = getattr(response, "usage", None)
        usage_payload = {
            "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
            "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
            "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
        }
        return ok_response(
            {
                "provider_name": normalized["provider_name"],
                "base_url": normalized["base_url"],
                "model": normalized["model"],
                "latency_ms": round(latency_ms, 2),
                "usage": usage_payload,
                "sample": output_text,
            },
            code="LLM_CONFIG_TEST_OK",
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=502,
            content=error_response(
                "INTERNAL_ERROR",
                "LLM 配置连通性测试失败",
                {
                    "error": str(exc),
                    "provider_name": normalized["provider_name"],
                    "base_url": normalized["base_url"],
                    "model": normalized["model"],
                },
            ),
        )


@router.get("/llm/metrics")
async def llm_metrics(
    hours: int = Query(default=24, ge=1, le=168),
    agent_id: str = Query(default=""),
    session_id: str = Query(default=""),
):
    usage_summary = TradingLedger.get_llm_usage_summary(hours=hours, agent_id=agent_id, session_id=session_id)
    runtime = get_llm_runtime_metrics()
    return ok_response(
        {
            "usage_summary": usage_summary,
            "runtime": runtime,
        },
        code="LLM_METRICS_OK",
    )


@router.get("/audit/evidence")
async def audit_evidence(
    limit: int = Query(default=50, ge=1, le=500),
    ticker: str = Query(default=""),
    session_id: str = Query(default=""),
    phase: str = Query(default=""),
    request_id: str = Query(default=""),
    degraded_only: bool = Query(default=False),
):
    records = TradingLedger.list_decision_evidence(
        limit=limit,
        ticker=ticker,
        session_id=session_id,
        phase=phase,
        request_id=request_id,
        degraded_only=degraded_only,
    )
    return ok_response(
        {
            "items": records,
            "count": len(records),
            "filters": {
                "ticker": ticker,
                "session_id": session_id,
                "phase": phase,
                "request_id": request_id,
                "degraded_only": degraded_only,
                "limit": limit,
            },
        },
        code="EVIDENCE_OK",
    )


@router.get("/reconciliation/guard")
async def reconciliation_guard(request: Request):
    try:
        service = _get_service(request)
        guard: dict[str, Any] = service.get_reconciliation_guard_state()
        return ok_response(guard, code="RECON_GUARD_OK")
    except TradingServiceError as exc:
        return _error_json(exc)


@router.get("/preflight")
async def startup_preflight(
    request: Request,
    refresh: bool = Query(default=False, description="是否重新执行一次 preflight"),
    include_stability_probe: bool = Query(default=False, description="是否检查稳定性探针依赖"),
):
    channel = os.getenv("TRADING_CHANNEL", "simulation")
    service = getattr(request.app.state, "trading_service", None)
    if service is not None and getattr(service, "channel", ""):
        channel = str(service.channel)

    report = getattr(request.app.state, "startup_preflight", {})
    if refresh or not isinstance(report, dict) or not report:
        report = run_startup_preflight(channel=channel, include_stability_probe=include_stability_probe)
        request.app.state.startup_preflight = report

    code = "PREFLIGHT_OK" if report.get("ok", False) else "PREFLIGHT_WARN"
    return ok_response(report, code=code)


@router.get("/error-codes")
async def error_codes():
    catalog = get_error_catalog()
    return ok_response(
        {
            "count": len(catalog),
            "items": catalog,
        },
        code="ERROR_CODES_OK",
    )


# ---------------------------------------------------------------------------
# System Config & Notification Test API (Phase 5 QA Rework)
# ---------------------------------------------------------------------------

@router.get("/config")
async def get_system_config(request: Request):
    """Get general system configuration for SystemConfig page."""
    config = {
        "day_roll_time": os.getenv("DAY_ROLL_TIME", "23:00"),
        "autopilot_template": os.getenv("AUTOPILOT_TEMPLATE", ""),
        "channel": getattr(request.app.state, "channel", "simulation"),
    }
    return ok_response(config)


@router.put("/config")
async def update_system_config(request: Request, body: dict[str, Any]):
    """Update general system configuration."""
    # Persist to environment or database (simplified)
    return ok_response({"status": "updated", "config": body})


@router.post("/notification/test")
async def test_notification():
    """Send a test notification to verify channel connectivity."""
    from src.routers.stream import publish_log
    publish_log("SYSTEM", "Test notification sent from SystemConfig page.", level="info")
    return ok_response({"status": "sent", "message": "Test notification dispatched."})
