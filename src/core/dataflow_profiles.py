from __future__ import annotations

import os
from typing import Any

DATAFLOW_PROFILE_ENV_KEYS: tuple[str, ...] = (
    "DATA_PROVIDER_RATE_LIMIT_PER_MINUTE",
    "DATA_PROVIDER_MIN_INTERVAL_MS",
    "DATA_PROVIDER_MAX_WAIT_MS",
    "DATA_PROVIDER_BACKOFF_RETRIES",
    "DATA_PROVIDER_BACKOFF_BASE_MS",
    "DATA_PROVIDER_BACKOFF_FACTOR",
    "DATA_PROVIDER_BACKOFF_MAX_MS",
    "DATA_QUALITY_ERROR_WARN",
    "DATA_QUALITY_ERROR_BLOCK",
    "DATA_QUALITY_EMPTY_WARN",
    "DATA_QUALITY_EMPTY_BLOCK",
    "DATA_QUALITY_RETRY_WARN",
    "DATA_QUALITY_RETRY_BLOCK",
    "DATA_QUALITY_RATE_LIMIT_WARN",
    "DATA_QUALITY_RATE_LIMIT_BLOCK",
    "DATA_QUALITY_STALE_WARN_DAYS",
    "DATA_QUALITY_STALE_BLOCK_DAYS",
    "DATA_QUALITY_PROVIDER_ERROR_WARN",
    "DATA_QUALITY_PROVIDER_ERROR_BLOCK",
    "DATA_QUALITY_PROVIDER_MIN_REQUESTS",
)

DATAFLOW_PROFILE_PRESETS: dict[str, dict[str, Any]] = {
    "dev_default": {
        "version": "2026.04.09.1",
        "description": "开发环境参数：容错优先，便于联调排错。",
        "env": {
            "DATA_PROVIDER_RATE_LIMIT_PER_MINUTE": "200",
            "DATA_PROVIDER_MIN_INTERVAL_MS": "60",
            "DATA_PROVIDER_MAX_WAIT_MS": "300",
            "DATA_PROVIDER_BACKOFF_RETRIES": "1",
            "DATA_PROVIDER_BACKOFF_BASE_MS": "40",
            "DATA_PROVIDER_BACKOFF_FACTOR": "1.8",
            "DATA_PROVIDER_BACKOFF_MAX_MS": "600",
            "DATA_QUALITY_ERROR_WARN": "0.25",
            "DATA_QUALITY_ERROR_BLOCK": "0.55",
            "DATA_QUALITY_EMPTY_WARN": "0.40",
            "DATA_QUALITY_EMPTY_BLOCK": "0.80",
            "DATA_QUALITY_RETRY_WARN": "0.30",
            "DATA_QUALITY_RETRY_BLOCK": "0.75",
            "DATA_QUALITY_RATE_LIMIT_WARN": "0.30",
            "DATA_QUALITY_RATE_LIMIT_BLOCK": "0.70",
            "DATA_QUALITY_STALE_WARN_DAYS": "5",
            "DATA_QUALITY_STALE_BLOCK_DAYS": "10",
            "DATA_QUALITY_PROVIDER_ERROR_WARN": "0.65",
            "DATA_QUALITY_PROVIDER_ERROR_BLOCK": "0.95",
            "DATA_QUALITY_PROVIDER_MIN_REQUESTS": "2",
        },
    },
    "sim_default": {
        "version": "2026.04.09.1",
        "description": "模拟交易参数：吞吐与稳定平衡。",
        "env": {
            "DATA_PROVIDER_RATE_LIMIT_PER_MINUTE": "120",
            "DATA_PROVIDER_MIN_INTERVAL_MS": "120",
            "DATA_PROVIDER_MAX_WAIT_MS": "400",
            "DATA_PROVIDER_BACKOFF_RETRIES": "2",
            "DATA_PROVIDER_BACKOFF_BASE_MS": "80",
            "DATA_PROVIDER_BACKOFF_FACTOR": "2.0",
            "DATA_PROVIDER_BACKOFF_MAX_MS": "1000",
            "DATA_QUALITY_ERROR_WARN": "0.15",
            "DATA_QUALITY_ERROR_BLOCK": "0.40",
            "DATA_QUALITY_EMPTY_WARN": "0.30",
            "DATA_QUALITY_EMPTY_BLOCK": "0.70",
            "DATA_QUALITY_RETRY_WARN": "0.20",
            "DATA_QUALITY_RETRY_BLOCK": "0.60",
            "DATA_QUALITY_RATE_LIMIT_WARN": "0.20",
            "DATA_QUALITY_RATE_LIMIT_BLOCK": "0.50",
            "DATA_QUALITY_STALE_WARN_DAYS": "3",
            "DATA_QUALITY_STALE_BLOCK_DAYS": "7",
            "DATA_QUALITY_PROVIDER_ERROR_WARN": "0.50",
            "DATA_QUALITY_PROVIDER_ERROR_BLOCK": "0.90",
            "DATA_QUALITY_PROVIDER_MIN_REQUESTS": "3",
        },
    },
    "prod_live": {
        "version": "2026.04.09.1",
        "description": "实盘参数：保守限流与退避，稳定优先。",
        "env": {
            "DATA_PROVIDER_RATE_LIMIT_PER_MINUTE": "90",
            "DATA_PROVIDER_MIN_INTERVAL_MS": "200",
            "DATA_PROVIDER_MAX_WAIT_MS": "1000",
            "DATA_PROVIDER_BACKOFF_RETRIES": "3",
            "DATA_PROVIDER_BACKOFF_BASE_MS": "120",
            "DATA_PROVIDER_BACKOFF_FACTOR": "2.5",
            "DATA_PROVIDER_BACKOFF_MAX_MS": "1500",
            "DATA_QUALITY_ERROR_WARN": "0.12",
            "DATA_QUALITY_ERROR_BLOCK": "0.30",
            "DATA_QUALITY_EMPTY_WARN": "0.25",
            "DATA_QUALITY_EMPTY_BLOCK": "0.60",
            "DATA_QUALITY_RETRY_WARN": "0.15",
            "DATA_QUALITY_RETRY_BLOCK": "0.45",
            "DATA_QUALITY_RATE_LIMIT_WARN": "0.12",
            "DATA_QUALITY_RATE_LIMIT_BLOCK": "0.35",
            "DATA_QUALITY_STALE_WARN_DAYS": "2",
            "DATA_QUALITY_STALE_BLOCK_DAYS": "5",
            "DATA_QUALITY_PROVIDER_ERROR_WARN": "0.40",
            "DATA_QUALITY_PROVIDER_ERROR_BLOCK": "0.75",
            "DATA_QUALITY_PROVIDER_MIN_REQUESTS": "5",
        },
    },
    "stress_probe": {
        "version": "2026.04.08.1",
        "description": "压测参数：用于稳定性压测，不建议长期实盘启用。",
        "env": {
            "DATA_PROVIDER_RATE_LIMIT_PER_MINUTE": "180",
            "DATA_PROVIDER_MIN_INTERVAL_MS": "50",
            "DATA_PROVIDER_MAX_WAIT_MS": "300",
            "DATA_PROVIDER_BACKOFF_RETRIES": "1",
            "DATA_PROVIDER_BACKOFF_BASE_MS": "40",
            "DATA_PROVIDER_BACKOFF_FACTOR": "1.8",
            "DATA_PROVIDER_BACKOFF_MAX_MS": "600",
            "DATA_QUALITY_ERROR_WARN": "0.20",
            "DATA_QUALITY_ERROR_BLOCK": "0.45",
            "DATA_QUALITY_EMPTY_WARN": "0.35",
            "DATA_QUALITY_EMPTY_BLOCK": "0.75",
            "DATA_QUALITY_RETRY_WARN": "0.25",
            "DATA_QUALITY_RETRY_BLOCK": "0.70",
            "DATA_QUALITY_RATE_LIMIT_WARN": "0.25",
            "DATA_QUALITY_RATE_LIMIT_BLOCK": "0.60",
            "DATA_QUALITY_STALE_WARN_DAYS": "3",
            "DATA_QUALITY_STALE_BLOCK_DAYS": "7",
            "DATA_QUALITY_PROVIDER_ERROR_WARN": "0.60",
            "DATA_QUALITY_PROVIDER_ERROR_BLOCK": "0.95",
            "DATA_QUALITY_PROVIDER_MIN_REQUESTS": "3",
        },
    },
}

DATAFLOW_PROFILE_ALIASES: dict[str, str] = {
    "dev": "dev_default",
    "development": "dev_default",
    "sim": "sim_default",
    "paper": "sim_default",
    "prod": "prod_live",
    "live": "prod_live",
    "ths_paper_default": "sim_default",
    "ths_live_safe": "prod_live",
}


def _normalize_profile_name(name: str) -> str:
    raw = str(name or "").strip().lower()
    if not raw:
        return raw
    return DATAFLOW_PROFILE_ALIASES.get(raw, raw)


def list_dataflow_profiles() -> dict[str, dict[str, Any]]:
    rows = {
        name: {
            "version": str(item.get("version", "1")),
            "description": str(item.get("description", "")),
            "env": dict(item.get("env", {})),
        }
        for name, item in DATAFLOW_PROFILE_PRESETS.items()
    }
    # Backward-compatible aliases expected by older scripts/tests.
    rows.setdefault(
        "ths_live_safe",
        {"version": rows["prod_live"]["version"], "description": rows["prod_live"]["description"], "env": dict(rows["prod_live"]["env"])},
    )
    rows.setdefault(
        "ths_paper_default",
        {"version": rows["sim_default"]["version"], "description": rows["sim_default"]["description"], "env": dict(rows["sim_default"]["env"])},
    )
    return rows


def get_dataflow_profile_meta(name: str) -> dict[str, str]:
    key = _normalize_profile_name(name)
    item = DATAFLOW_PROFILE_PRESETS.get(key)
    if not item:
        return {}
    return {
        "name": key,
        "version": str(item.get("version", "1")),
        "description": str(item.get("description", "")),
    }


def resolve_dataflow_profile(name: str) -> dict[str, str] | None:
    key = _normalize_profile_name(name)
    payload = DATAFLOW_PROFILE_PRESETS.get(key)
    if not payload:
        return None
    env_map = payload.get("env", {}) or {}
    return {str(k): str(v) for k, v in env_map.items() if str(k)}


def current_dataflow_env_snapshot() -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for key in DATAFLOW_PROFILE_ENV_KEYS:
        snapshot[key] = str(os.getenv(key, ""))
    return snapshot


def apply_dataflow_env(env_values: dict[str, Any]) -> dict[str, str]:
    applied: dict[str, str] = {}
    for key, value in (env_values or {}).items():
        name = str(key or "").strip()
        if not name:
            continue
        text = str(value)
        os.environ[name] = text
        applied[name] = text
    return applied


def diff_profile_against_current(name: str) -> dict[str, dict[str, str]]:
    profile_env = resolve_dataflow_profile(name)
    if profile_env is None:
        return {}
    current = current_dataflow_env_snapshot()
    diff: dict[str, dict[str, str]] = {}
    for key, expected in profile_env.items():
        current_value = current.get(key, "")
        if str(current_value) == str(expected):
            continue
        diff[key] = {"current": str(current_value), "profile": str(expected)}
    return diff
