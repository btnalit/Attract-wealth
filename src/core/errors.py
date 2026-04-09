"""
Unified business error codes and response helpers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ERROR_CODE_CATALOG: dict[str, dict[str, Any]] = {
    "OK": {"category": "common", "retryable": False, "http_status": 200, "desc": "request succeeded"},
    "INTERNAL_ERROR": {"category": "system", "retryable": True, "http_status": 500, "desc": "internal error"},
    "SERVICE_NOT_READY": {"category": "system", "retryable": True, "http_status": 503, "desc": "service not ready"},
    "EVENT_ENGINE_NOT_READY": {
        "category": "system",
        "retryable": True,
        "http_status": 503,
        "desc": "event engine not ready",
    },
    "BROKER_UNAVAILABLE": {
        "category": "channel",
        "retryable": True,
        "http_status": 503,
        "desc": "broker unavailable",
    },
    "CHANNEL_MISMATCH": {
        "category": "channel",
        "retryable": False,
        "http_status": 409,
        "desc": "requested channel does not match active channel",
    },
    "PREFLIGHT_FAILED": {
        "category": "system",
        "retryable": False,
        "http_status": 503,
        "desc": "startup preflight failed",
    },
    "RISK_REJECTED": {"category": "risk", "retryable": False, "http_status": 409, "desc": "risk check rejected"},
    "INVALID_ORDER_REQUEST": {
        "category": "validation",
        "retryable": False,
        "http_status": 400,
        "desc": "invalid order request",
    },
    "IDEMPOTENCY_CONFLICT": {
        "category": "validation",
        "retryable": False,
        "http_status": 409,
        "desc": "idempotency key conflicts with existing payload",
    },
    "ORDER_REJECTED": {"category": "channel", "retryable": False, "http_status": 409, "desc": "order rejected"},
    "ORDER_FAILED": {"category": "channel", "retryable": True, "http_status": 502, "desc": "order failed"},
    "ORDER_TRACE_NOT_FOUND": {
        "category": "query",
        "retryable": False,
        "http_status": 404,
        "desc": "order trace not found",
    },
    "DIRECT_ORDER_MANUAL_CONFIRM_REQUIRED": {
        "category": "risk",
        "retryable": False,
        "http_status": 403,
        "desc": "manual confirmation required for direct order",
    },
    "DIRECT_ORDER_TICKER_NOT_ALLOWED": {
        "category": "risk",
        "retryable": False,
        "http_status": 403,
        "desc": "ticker is not in direct order whitelist",
    },
    "DIRECT_ORDER_RATE_LIMITED": {
        "category": "risk",
        "retryable": True,
        "http_status": 429,
        "desc": "direct order rate limit exceeded",
    },
    "DIRECT_ORDER_NOTIONAL_LIMIT": {
        "category": "risk",
        "retryable": False,
        "http_status": 409,
        "desc": "single direct order notional exceeds limit",
    },
    "DIRECT_ORDER_DAILY_LIMIT_EXCEEDED": {
        "category": "risk",
        "retryable": False,
        "http_status": 409,
        "desc": "daily direct order notional exceeds limit",
    },
    "DIRECT_ORDER_WINDOW_CLOSED": {
        "category": "risk",
        "retryable": False,
        "http_status": 409,
        "desc": "trading window is closed for direct order",
    },
    "RECON_OK": {"category": "reconciliation", "retryable": False, "http_status": 200, "desc": "reconciliation ok"},
    "RECON_WARN": {
        "category": "reconciliation",
        "retryable": False,
        "http_status": 200,
        "desc": "reconciliation warning",
    },
    "RECON_BLOCK": {
        "category": "reconciliation",
        "retryable": False,
        "http_status": 409,
        "desc": "reconciliation blocked",
    },
    "RECON_BLOCKED": {
        "category": "reconciliation",
        "retryable": False,
        "http_status": 409,
        "desc": "reconciliation guard is blocking",
    },
    "RECON_UNLOCKED": {
        "category": "reconciliation",
        "retryable": False,
        "http_status": 200,
        "desc": "reconciliation unlocked",
    },
    "RECON_UNLOCK_NOOP": {
        "category": "reconciliation",
        "retryable": False,
        "http_status": 200,
        "desc": "reconciliation guard was not blocked",
    },
    "UNAUTHORIZED_UNLOCK": {"category": "auth", "retryable": False, "http_status": 403, "desc": "unauthorized unlock"},
    "DAY_ROLL_RECON_BLOCK": {
        "category": "reconciliation",
        "retryable": False,
        "http_status": 409,
        "desc": "day roll blocked by reconciliation guard",
    },
    "NON_TRADING_DAY_SKIP": {
        "category": "calendar",
        "retryable": False,
        "http_status": 200,
        "desc": "non-trading day skipped",
    },
    "INVALID_AUTOPILOT_TEMPLATE": {
        "category": "validation",
        "retryable": False,
        "http_status": 400,
        "desc": "invalid autopilot template",
    },
    "INVALID_STRATEGY_REQUEST": {
        "category": "strategy",
        "retryable": False,
        "http_status": 400,
        "desc": "invalid strategy request",
    },
    "STRATEGY_NOT_FOUND": {
        "category": "strategy",
        "retryable": False,
        "http_status": 404,
        "desc": "strategy not found",
    },
    "STRATEGY_VERSION_GATE_FAILED": {
        "category": "strategy",
        "retryable": False,
        "http_status": 409,
        "desc": "strategy gate failed",
    },
    "STRATEGY_CANDIDATE_GATE_FAILED": {
        "category": "strategy",
        "retryable": False,
        "http_status": 409,
        "desc": "candidate gate failed",
    },
    "STRATEGY_STATUS_TRANSITION_INVALID": {
        "category": "strategy",
        "retryable": False,
        "http_status": 409,
        "desc": "strategy status transition invalid",
    },
    "STRATEGY_BACKTEST_REPORT_NOT_FOUND": {
        "category": "strategy",
        "retryable": False,
        "http_status": 404,
        "desc": "backtest report not found",
    },
}


@dataclass
class TradingServiceError(Exception):
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    http_status: int = 400

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


def get_error_catalog() -> dict[str, dict[str, Any]]:
    return dict(ERROR_CODE_CATALOG)


def get_error_meta(code: str) -> dict[str, Any]:
    return ERROR_CODE_CATALOG.get(
        code,
        {
            "category": "unknown",
            "retryable": False,
            "http_status": 400,
            "desc": "unregistered error code",
        },
    )


def ok_response(data: Any, code: str = "OK") -> dict[str, Any]:
    return {"ok": True, "code": code, "data": data}


def error_response(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "ok": False,
        "code": code,
        "message": message,
        "details": details or {},
        "meta": get_error_meta(code),
    }
