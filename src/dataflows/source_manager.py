"""
Unified data source manager with fallback, cache, and data quality metrics.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Any, Callable

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except Exception:  # noqa: BLE001
    PANDAS_AVAILABLE = False

    class _PandasCompatDataFrame(list):
        def __init__(self, rows: list[dict[str, Any]] | None = None):
            super().__init__(rows or [])
            self.columns = list(self[0].keys()) if self else []
            self.index = []

        @property
        def empty(self) -> bool:
            return len(self) == 0

        def reset_index(self, drop: bool = False):  # noqa: ARG002
            return self

        def copy(self):
            return _PandasCompatDataFrame(list(self))

    class _PandasCompatRangeIndex(list):
        pass

    class _PandasCompatDatetimeIndex(list):
        def max(self):
            return None

    class _PandasCompatTimestamp:
        def __init__(self, value: Any = None):
            self.value = value

        def isoformat(self) -> str:
            return str(self.value) if self.value is not None else ""

    class _PandasCompatModule:
        DataFrame = _PandasCompatDataFrame
        RangeIndex = _PandasCompatRangeIndex
        DatetimeIndex = _PandasCompatDatetimeIndex
        Timestamp = _PandasCompatTimestamp

        @staticmethod
        def to_datetime(values: Any, errors: str = "coerce"):  # noqa: ARG004
            return values

        @staticmethod
        def isna(value: Any) -> bool:
            return value is None

    pd = _PandasCompatModule()

from src.dataflows.cache.manager import CacheManager, cache_manager

logger = logging.getLogger(__name__)


class BaseDataSource(ABC):
    """Standardized provider contract."""

    @abstractmethod
    def get_kline(self, ticker: str, start_date: str, end_date: str, timeframe: str = "D") -> pd.DataFrame:
        """Return K-line dataframe."""

    @abstractmethod
    def get_fundamentals(self, ticker: str) -> dict:
        """Return fundamentals."""

    @abstractmethod
    def get_news(self, ticker: str, limit: int = 10) -> list[dict]:
        """Return related news."""


class DataSourceManager:
    """Provider registry with fallback strategy and observability."""

    def __init__(
        self,
        cache: CacheManager | None = None,
        *,
        stale_kline_days: int = 5,
        auto_switch_on_success: bool = True,
    ):
        self._providers: dict[str, BaseDataSource] = {}
        self._priorities: dict[str, int] = {}
        self._enabled: dict[str, bool] = {}
        self._current_provider_name: str | None = None
        self._lock = threading.RLock()
        self._cache = cache
        self._stale_kline_days = max(1, int(stale_kline_days))
        self._auto_switch_on_success = auto_switch_on_success
        self._cache_ttl = {
            "kline": 120,
            "fundamentals": 600,
            "news": 120,
        }
        self._provider_rate_limit = self._load_provider_rate_limit_from_env()
        self._retry_policy = self._load_retry_policy_from_env()
        self._provider_runtime: dict[str, dict[str, Any]] = {}
        self._quality_thresholds = self._load_quality_thresholds_from_env()
        self._quality_feedback: dict[str, Any] = {
            "true_positive": 0,
            "false_positive": 0,
            "false_negative": 0,
            "updated_at": 0.0,
            "events_total": 0,
        }
        self._quality_event_history: list[dict[str, Any]] = []
        self._quality_event_history_limit = 500
        self._quality_event_seq = 0
        self._quality_last_signature = ""
        self._quality_last_event_id = ""
        self._quality_last_event_ts = 0.0
        self._metrics: dict[str, Any] = {
            "requests_total": 0,
            "success_total": 0,
            "failure_total": 0,
            "fallback_total": 0,
            "empty_total": 0,
            "stale_kline_total": 0,
            "rate_limited_total": 0,
            "retries_total": 0,
            "retry_success_total": 0,
            "throttle_sleep_ms_total": 0.0,
            "backoff_sleep_ms_total": 0.0,
            "cache_requests": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "cache_decode_errors": 0,
            "cache_last_error_code": "",
            "cache_last_error": "",
            "last_success_ts": 0.0,
            "last_failure_ts": 0.0,
            "last_failure_code": "",
            "last_failure_message": "",
            "kline_last_age_days": None,
            "methods": {
                "get_kline": {
                    "requests": 0,
                    "success": 0,
                    "failure": 0,
                    "fallback": 0,
                    "empty": 0,
                    "retries": 0,
                    "rate_limited": 0,
                },
                "get_fundamentals": {
                    "requests": 0,
                    "success": 0,
                    "failure": 0,
                    "fallback": 0,
                    "empty": 0,
                    "retries": 0,
                    "rate_limited": 0,
                },
                "get_news": {
                    "requests": 0,
                    "success": 0,
                    "failure": 0,
                    "fallback": 0,
                    "empty": 0,
                    "retries": 0,
                    "rate_limited": 0,
                },
            },
            "providers": {},
        }

    # -------------------------
    # Provider registry
    # -------------------------
    def register(
        self,
        name: str,
        provider: BaseDataSource,
        *,
        priority: int = 100,
        is_primary: bool = False,
        enabled: bool = True,
    ) -> None:
        provider_name = name.strip().lower()
        if not provider_name:
            raise ValueError("provider name is empty")

        with self._lock:
            self._providers[provider_name] = provider
            self._priorities[provider_name] = int(priority)
            self._enabled[provider_name] = bool(enabled)
            if self._current_provider_name is None or is_primary:
                self._current_provider_name = provider_name
            self._provider_bucket(provider_name).update(
                {
                    "enabled": bool(enabled),
                    "priority": int(priority),
                }
            )
            self._provider_runtime_bucket(provider_name)

    def enable(self, name: str, enabled: bool = True) -> None:
        provider_name = name.strip().lower()
        with self._lock:
            if provider_name not in self._providers:
                raise ValueError(f"Provider {provider_name} not registered.")
            self._enabled[provider_name] = bool(enabled)
            self._provider_bucket(provider_name)["enabled"] = bool(enabled)

    def use(self, name: str) -> None:
        provider_name = name.strip().lower()
        with self._lock:
            if provider_name not in self._providers:
                raise ValueError(f"Provider {provider_name} not registered.")
            if not self._enabled.get(provider_name, False):
                raise ValueError(f"Provider {provider_name} is disabled.")
            self._current_provider_name = provider_name

    @property
    def provider(self) -> BaseDataSource:
        with self._lock:
            if self._current_provider_name and self._enabled.get(self._current_provider_name, False):
                return self._providers[self._current_provider_name]
            for name in self._ordered_provider_names():
                return self._providers[name]
            raise RuntimeError("No data provider available.")

    def list_providers(self) -> list[dict[str, Any]]:
        with self._lock:
            ordered = self._ordered_provider_names(include_disabled=True)
            result = []
            for name in ordered:
                result.append(
                    {
                        "name": name,
                        "priority": self._priorities.get(name, 100),
                        "enabled": bool(self._enabled.get(name, False)),
                        "current": name == self._current_provider_name,
                    }
                )
            return result

    def get_current_provider_name(self) -> str:
        """Return current active provider name, empty string when unavailable."""
        with self._lock:
            if self._current_provider_name and self._enabled.get(self._current_provider_name, False):
                return self._current_provider_name
            ordered = self._ordered_provider_names()
            return ordered[0] if ordered else ""

    def get_provider_instance(self, name: str | None = None) -> BaseDataSource | None:
        """Return provider instance by name or current active provider."""
        target = str(name or "").strip().lower()
        with self._lock:
            provider_name = target or self.get_current_provider_name()
            if not provider_name:
                return None
            return self._providers.get(provider_name)

    # -------------------------
    # Public query methods
    # -------------------------
    def get_kline(self, ticker: str, start_date: str, end_date: str, timeframe: str = "D") -> pd.DataFrame:
        method = "get_kline"
        cache_key = f"kline:{ticker}:{start_date}:{end_date}:{timeframe}"
        cached_df = self._cache_get_dataframe(cache_key)
        if cached_df is not None:
            self._track_kline_freshness(cached_df)
            return cached_df

        result = self._call_with_fallback(
            method=method,
            request=lambda provider: provider.get_kline(ticker, start_date, end_date, timeframe),
            validator=lambda value: isinstance(value, pd.DataFrame),
            empty=lambda value: value.empty,
            default_factory=pd.DataFrame,
        )
        self._track_kline_freshness(result)
        if not result.empty:
            self._cache_set_dataframe(cache_key, result, ttl=self._cache_ttl["kline"])
        return result

    def get_fundamentals(self, ticker: str) -> dict:
        method = "get_fundamentals"
        cache_key = f"fundamentals:{ticker}"
        cached = self._cache_get(cache_key)
        if isinstance(cached, dict):
            return cached

        result = self._call_with_fallback(
            method=method,
            request=lambda provider: provider.get_fundamentals(ticker),
            validator=lambda value: isinstance(value, dict),
            empty=lambda value: len(value) == 0,
            default_factory=dict,
        )
        if result:
            self._cache_set(cache_key, result, ttl=self._cache_ttl["fundamentals"])
        return result

    def get_news(self, ticker: str, limit: int = 10) -> list[dict]:
        method = "get_news"
        cache_key = f"news:{ticker}:{int(limit)}"
        cached = self._cache_get(cache_key)
        if isinstance(cached, list):
            return cached

        result = self._call_with_fallback(
            method=method,
            request=lambda provider: provider.get_news(ticker, limit),
            validator=lambda value: isinstance(value, list),
            empty=lambda value: len(value) == 0,
            default_factory=list,
        )
        if result:
            self._cache_set(cache_key, result, ttl=self._cache_ttl["news"])
        return result

    def record_quality_feedback(
        self,
        *,
        label: str,
        event_id: str = "",
        source: str = "api",
        note: str = "",
    ) -> dict[str, Any]:
        normalized = self._normalize_feedback_label(label)
        if not normalized:
            raise ValueError(f"unsupported feedback label: {label}")

        now = time.time()
        with self._lock:
            self._quality_feedback[normalized] = int(self._quality_feedback.get(normalized, 0)) + 1
            self._quality_feedback["events_total"] = int(self._quality_feedback.get("events_total", 0)) + 1
            self._quality_feedback["updated_at"] = now
            self._quality_event_history.append(
                {
                    "event_id": str(event_id or ""),
                    "label": normalized,
                    "source": str(source or "api"),
                    "note": str(note or ""),
                    "timestamp": now,
                }
            )
            if len(self._quality_event_history) > self._quality_event_history_limit:
                self._quality_event_history = self._quality_event_history[-self._quality_event_history_limit :]
            return self._build_quality_feedback_metrics_locked()

    def get_quality_feedback_metrics(self) -> dict[str, Any]:
        with self._lock:
            return self._build_quality_feedback_metrics_locked()

    def list_quality_events(self, limit: int = 50) -> list[dict[str, Any]]:
        n = max(1, int(limit))
        with self._lock:
            return list(self._quality_event_history[-n:])[::-1]

    # -------------------------
    # Metrics and quality
    # -------------------------
    def get_runtime_config(self) -> dict[str, Any]:
        with self._lock:
            return {
                "provider_rate_limit": dict(self._provider_rate_limit),
                "retry_policy": dict(self._retry_policy),
                "quality_thresholds": dict(self._quality_thresholds),
                "cache_ttl": dict(self._cache_ttl),
            }

    def reload_runtime_config_from_env(self) -> dict[str, Any]:
        with self._lock:
            self._provider_rate_limit = self._load_provider_rate_limit_from_env()
            self._retry_policy = self._load_retry_policy_from_env()
            self._quality_thresholds = self._load_quality_thresholds_from_env()
            self._provider_runtime = {}
        return self.get_runtime_config()

    def reset_metrics(self) -> None:
        with self._lock:
            method_keys = tuple(self._metrics["methods"].keys())
            providers = list(self._providers.keys())
            self._metrics = {
                "requests_total": 0,
                "success_total": 0,
                "failure_total": 0,
                "fallback_total": 0,
                "empty_total": 0,
                "stale_kline_total": 0,
                "rate_limited_total": 0,
                "retries_total": 0,
                "retry_success_total": 0,
                "throttle_sleep_ms_total": 0.0,
                "backoff_sleep_ms_total": 0.0,
                "cache_requests": 0,
                "cache_hits": 0,
                "cache_misses": 0,
                "cache_decode_errors": 0,
                "cache_last_error_code": "",
                "cache_last_error": "",
                "last_success_ts": 0.0,
                "last_failure_ts": 0.0,
                "last_failure_code": "",
                "last_failure_message": "",
                "kline_last_age_days": None,
                "methods": {
                    key: {
                        "requests": 0,
                        "success": 0,
                        "failure": 0,
                        "fallback": 0,
                        "empty": 0,
                        "retries": 0,
                        "rate_limited": 0,
                    }
                    for key in method_keys
                },
                "providers": {},
            }
            for provider_name in providers:
                self._provider_bucket(provider_name).update(
                    {
                        "enabled": self._enabled.get(provider_name, True),
                        "priority": self._priorities.get(provider_name, 100),
                    }
                )
            self._provider_runtime = {}
            if self._cache:
                self._cache.reset_metrics()

    def get_metrics(self) -> dict[str, Any]:
        with self._lock:
            total_requests = int(self._metrics["requests_total"])
            success_total = int(self._metrics["success_total"])
            failure_total = int(self._metrics["failure_total"])
            empty_total = int(self._metrics["empty_total"])
            fallback_total = int(self._metrics["fallback_total"])
            retries_total = int(self._metrics["retries_total"])
            retry_success_total = int(self._metrics["retry_success_total"])
            rate_limited_total = int(self._metrics["rate_limited_total"])
            throttle_sleep_ms_total = float(self._metrics["throttle_sleep_ms_total"])
            backoff_sleep_ms_total = float(self._metrics["backoff_sleep_ms_total"])

            error_rate = failure_total / total_requests if total_requests else 0.0
            empty_rate = empty_total / total_requests if total_requests else 0.0
            fallback_rate = fallback_total / success_total if success_total else 0.0
            # Use successful-retry ratio for quality/tuning to avoid
            # over-penalizing a single request that exhausts retries
            # before falling back to another provider.
            retry_rate = retry_success_total / total_requests if total_requests else 0.0
            retry_pressure_rate = retries_total / total_requests if total_requests else 0.0
            rate_limited_rate = rate_limited_total / total_requests if total_requests else 0.0
            local_cache_requests = int(self._metrics["cache_requests"])
            local_cache_hits = int(self._metrics["cache_hits"])
            local_cache_hit_rate = local_cache_hits / local_cache_requests if local_cache_requests else 0.0

            providers = {
                name: {
                    **bucket,
                    "error_rate": round(bucket["failure"] / bucket["requests"], 4) if bucket["requests"] else 0.0,
                    "empty_rate": round(bucket["empty"] / bucket["requests"], 4) if bucket["requests"] else 0.0,
                    "retry_rate": round(bucket["retries"] / bucket["requests"], 4) if bucket["requests"] else 0.0,
                    "rate_limited_rate": round(bucket["rate_limited"] / bucket["requests"], 4)
                    if bucket["requests"]
                    else 0.0,
                }
                for name, bucket in self._metrics["providers"].items()
            }

            quality = self._build_quality_snapshot(
                error_rate=error_rate,
                empty_rate=empty_rate,
                retry_rate=retry_rate,
                rate_limited_rate=rate_limited_rate,
                providers=providers,
                kline_last_age_days=self._metrics["kline_last_age_days"],
            )
            quality_event = self._register_quality_event(quality)
            quality_feedback = self._build_quality_feedback_metrics_locked()
            tuning = self._build_tuning_snapshot(
                error_rate=error_rate,
                retry_rate=retry_rate,
                rate_limited_rate=rate_limited_rate,
                quality=quality,
            )
            runtime_config = self.get_runtime_config()
            summary = {
                "current_provider": self._current_provider_name,
                "requests_total": total_requests,
                "error_rate": round(error_rate, 4),
                "empty_rate": round(empty_rate, 4),
                "fallback_rate": round(fallback_rate, 4),
                "retry_rate": round(retry_rate, 4),
                "retry_pressure_rate": round(retry_pressure_rate, 4),
                "rate_limited_rate": round(rate_limited_rate, 4),
                "cache_hit_rate": round(local_cache_hit_rate, 4),
                "quality_alert_level": quality["alert_level"],
                "quality_code": quality["code"],
                "quality_action": quality["action"],
                "quality_event_id": quality_event.get("event_id", ""),
                "tuning_action": tuning["action"],
                "quality_feedback_precision": quality_feedback.get("precision", 0.0),
                "quality_false_positive_rate": quality_feedback.get("false_positive_rate", 0.0),
                "quality_miss_rate": quality_feedback.get("miss_rate", 0.0),
                "last_failure_code": str(self._metrics.get("last_failure_code", "")),
            }

            return {
                "current_provider": self._current_provider_name,
                "providers": providers,
                "provider_order": self.list_providers(),
                "requests_total": total_requests,
                "success_total": success_total,
                "failure_total": failure_total,
                "fallback_total": fallback_total,
                "empty_total": empty_total,
                "stale_kline_total": int(self._metrics["stale_kline_total"]),
                "kline_last_age_days": self._metrics["kline_last_age_days"],
                "error_rate": round(error_rate, 4),
                "empty_rate": round(empty_rate, 4),
                "fallback_rate": round(fallback_rate, 4),
                "retries_total": retries_total,
                "retry_success_total": retry_success_total,
                "retry_rate": round(retry_rate, 4),
                "retry_pressure_rate": round(retry_pressure_rate, 4),
                "rate_limited_total": rate_limited_total,
                "rate_limited_rate": round(rate_limited_rate, 4),
                "throttle_sleep_ms_total": round(throttle_sleep_ms_total, 3),
                "backoff_sleep_ms_total": round(backoff_sleep_ms_total, 3),
                "last_failure_code": str(self._metrics.get("last_failure_code", "")),
                "last_failure_message": str(self._metrics.get("last_failure_message", "")),
                "methods": self._metrics["methods"],
                "local_cache": {
                    "requests": local_cache_requests,
                    "hits": local_cache_hits,
                    "misses": int(self._metrics["cache_misses"]),
                    "hit_rate": round(local_cache_hit_rate, 4),
                    "decode_errors": int(self._metrics["cache_decode_errors"]),
                    "last_error_code": str(self._metrics.get("cache_last_error_code", "")),
                    "last_error": str(self._metrics.get("cache_last_error", "")),
                },
                "summary": summary,
                "quality": quality,
                "tuning": tuning,
                "quality_event": quality_event,
                "quality_feedback": quality_feedback,
                "quality_events": self.list_quality_events(limit=50),
                "runtime_config": runtime_config,
                "cache": self._cache.get_metrics() if self._cache else {},
            }

    # -------------------------
    # Internal fallback engine
    # -------------------------
    def _call_with_fallback(
        self,
        *,
        method: str,
        request: Callable[[BaseDataSource], Any],
        validator: Callable[[Any], bool],
        empty: Callable[[Any], bool],
        default_factory: Callable[[], Any],
    ) -> Any:
        with self._lock:
            self._metrics["requests_total"] += 1
            self._metrics["methods"][method]["requests"] += 1
            candidates = self._ordered_provider_names()

        if not candidates:
            with self._lock:
                self._metrics["failure_total"] += 1
                self._metrics["methods"][method]["failure"] += 1
                self._metrics["last_failure_ts"] = time.time()
                self._metrics["last_failure_code"] = "NO_PROVIDER_AVAILABLE"
                self._metrics["last_failure_message"] = f"{method}:no_enabled_provider"
            return default_factory()

        for index, provider_name in enumerate(candidates):
            provider = self._providers[provider_name]
            bucket = self._provider_bucket(provider_name)
            bucket["requests"] += 1

            allowed, throttle_wait_seconds, limit_reason = self._consume_provider_rate_limit(provider_name)
            if not allowed:
                now = time.time()
                with self._lock:
                    self._metrics["rate_limited_total"] += 1
                    self._metrics["methods"][method]["rate_limited"] += 1
                bucket["rate_limited"] += 1
                bucket["last_failure_ts"] = now
                bucket["last_rate_limit_reason"] = limit_reason
                bucket["last_error_code"] = "RATE_LIMITED"
                bucket["last_error"] = f"rate_limited:{limit_reason}"
                with self._lock:
                    self._metrics["last_failure_code"] = "RATE_LIMITED"
                    self._metrics["last_failure_message"] = f"{provider_name}:{method}:{limit_reason}"
                continue

            if throttle_wait_seconds > 0:
                time.sleep(throttle_wait_seconds)
                slept_ms = throttle_wait_seconds * 1000
                bucket["throttle_sleep_ms"] += slept_ms
                with self._lock:
                    self._metrics["throttle_sleep_ms_total"] += slept_ms

            max_retries = int(self._retry_policy["max_retries"])
            attempt = 0
            while True:
                start = time.perf_counter()
                try:
                    value = request(provider)
                except Exception as exc:  # noqa: BLE001
                    latency_ms = (time.perf_counter() - start) * 1000
                    bucket["last_latency_ms"] = round(latency_ms, 3)
                    if attempt < max_retries:
                        backoff_seconds = self._compute_backoff_seconds(attempt)
                        with self._lock:
                            self._metrics["retries_total"] += 1
                            self._metrics["methods"][method]["retries"] += 1
                            self._metrics["backoff_sleep_ms_total"] += backoff_seconds * 1000
                        bucket["retries"] += 1
                        bucket["backoff_sleep_ms"] += backoff_seconds * 1000
                        bucket["last_error_code"] = "RETRYING"
                        bucket["last_error"] = f"retrying:{exc}"
                        time.sleep(backoff_seconds)
                        attempt += 1
                        continue

                    bucket["failure"] += 1
                    bucket["last_failure_ts"] = time.time()
                    bucket["last_error_code"] = "PROVIDER_EXCEPTION"
                    bucket["last_error"] = str(exc)
                    with self._lock:
                        self._metrics["last_failure_code"] = "PROVIDER_EXCEPTION"
                        self._metrics["last_failure_message"] = f"{provider_name}:{method}:{exc}"
                    logger.warning(
                        "data source call failed: provider=%s method=%s retries=%s err=%s",
                        provider_name,
                        method,
                        attempt,
                        exc,
                    )
                    break

                latency_ms = (time.perf_counter() - start) * 1000
                bucket["last_latency_ms"] = round(latency_ms, 3)

                if not validator(value):
                    bucket["failure"] += 1
                    bucket["last_failure_ts"] = time.time()
                    bucket["last_error_code"] = "INVALID_PAYLOAD"
                    bucket["last_error"] = f"{method} returned invalid payload"
                    with self._lock:
                        self._metrics["last_failure_code"] = "INVALID_PAYLOAD"
                        self._metrics["last_failure_message"] = f"{provider_name}:{method}:invalid_payload"
                    break

                if empty(value):
                    bucket["empty"] += 1
                    bucket["last_error_code"] = "EMPTY_PAYLOAD"
                    bucket["last_error"] = f"{method} returned empty payload"
                    break

                bucket["success"] += 1
                bucket["last_success_ts"] = time.time()
                bucket["last_error_code"] = ""
                bucket["last_error"] = ""
                if attempt > 0:
                    bucket["retry_success"] += 1
                    with self._lock:
                        self._metrics["retry_success_total"] += 1

                with self._lock:
                    self._metrics["success_total"] += 1
                    self._metrics["methods"][method]["success"] += 1
                    self._metrics["last_success_ts"] = time.time()
                    if index > 0:
                        self._metrics["fallback_total"] += 1
                        self._metrics["methods"][method]["fallback"] += 1
                        bucket["fallback_success"] += 1
                    if self._auto_switch_on_success:
                        self._current_provider_name = provider_name

                return value

        with self._lock:
            self._metrics["failure_total"] += 1
            self._metrics["methods"][method]["failure"] += 1
            self._metrics["empty_total"] += 1
            self._metrics["methods"][method]["empty"] += 1
            self._metrics["last_failure_ts"] = time.time()
            self._metrics["last_failure_code"] = "ALL_PROVIDERS_FAILED"
            self._metrics["last_failure_message"] = f"{method}:all_providers_failed"
        return default_factory()

    # -------------------------
    # Internal cache helpers
    # -------------------------
    def _cache_get(self, key: str) -> Any:
        if not self._cache:
            return None
        with self._lock:
            self._metrics["cache_requests"] += 1
        value = self._cache.get(key)
        with self._lock:
            if value is None:
                self._metrics["cache_misses"] += 1
            else:
                self._metrics["cache_hits"] += 1
        return value

    def _cache_set(self, key: str, value: Any, ttl: int) -> None:
        if self._cache:
            self._cache.set(key, value, ttl=ttl)

    def _cache_get_dataframe(self, key: str) -> pd.DataFrame | None:
        payload = self._cache_get(key)
        if not isinstance(payload, dict) or payload.get("__type__") != "dataframe":
            return None
        try:
            records = payload.get("records", [])
            columns = payload.get("columns", [])
            if not isinstance(records, list) or not isinstance(columns, list):
                self._mark_cache_decode_error("INVALID_CACHE_PAYLOAD", f"{key}:invalid_records_or_columns")
                return None
            return pd.DataFrame.from_records(records, columns=columns)
        except Exception as exc:  # noqa: BLE001
            self._mark_cache_decode_error("CACHE_DESERIALIZE_EXCEPTION", f"{key}:{exc}")
            return None

    def _cache_set_dataframe(self, key: str, df: pd.DataFrame, ttl: int) -> None:
        if df.empty:
            return
        payload = {
            "__type__": "dataframe",
            "columns": [str(column) for column in df.columns],
            "records": [{str(k): self._json_safe(v) for k, v in row.items()} for row in df.to_dict(orient="records")],
        }
        self._cache_set(key, payload, ttl=ttl)

    # -------------------------
    # Internal quality helpers
    # -------------------------
    def _track_kline_freshness(self, df: pd.DataFrame) -> None:
        if df.empty:
            return
        latest = self._extract_latest_datetime(df)
        if latest is None:
            return

        age_days = max(0, (datetime.now().date() - latest.date()).days)
        with self._lock:
            self._metrics["kline_last_age_days"] = age_days
            if age_days > self._stale_kline_days:
                self._metrics["stale_kline_total"] += 1

    @staticmethod
    def _extract_latest_datetime(df: pd.DataFrame) -> datetime | None:
        for column in ("date", "datetime", "trade_date"):
            if column not in df.columns:
                continue
            series = pd.to_datetime(df[column], errors="coerce")
            series = series.dropna()
            if not series.empty:
                value = series.iloc[-1]
                if isinstance(value, pd.Timestamp):
                    return value.to_pydatetime()
                if isinstance(value, datetime):
                    return value
        if isinstance(df.index, pd.DatetimeIndex) and len(df.index) > 0:
            return df.index.max().to_pydatetime()
        return None

    def _ordered_provider_names(self, include_disabled: bool = False) -> list[str]:
        names = list(self._providers.keys())
        if not include_disabled:
            names = [name for name in names if self._enabled.get(name, False)]
        names.sort(key=lambda provider_name: self._priorities.get(provider_name, 100))

        current = self._current_provider_name
        if current and current in names:
            names.remove(current)
            names.insert(0, current)
        return names

    def _consume_provider_rate_limit(self, provider_name: str) -> tuple[bool, float, str]:
        now = time.time()
        per_minute = int(self._provider_rate_limit["per_minute"])
        min_interval_seconds = float(self._provider_rate_limit["min_interval_ms"]) / 1000.0
        max_wait_seconds = float(self._provider_rate_limit["max_wait_ms"]) / 1000.0

        with self._lock:
            runtime = self._provider_runtime_bucket(provider_name)
            window_start = float(runtime["window_start_ts"])
            if window_start <= 0 or now - window_start >= 60.0:
                runtime["window_start_ts"] = now
                runtime["window_count"] = 0
                window_start = now

            wait_interval = max(0.0, float(runtime["last_request_ts"]) + min_interval_seconds - now)
            wait_quota = 0.0
            reason = "interval"
            if per_minute > 0 and int(runtime["window_count"]) >= per_minute:
                wait_quota = max(0.0, 60.0 - (now - window_start))
                reason = "per_minute"
            wait_seconds = max(wait_interval, wait_quota)
            if wait_seconds > max_wait_seconds:
                return False, wait_seconds, reason

            runtime["last_request_ts"] = now + wait_seconds
            if per_minute > 0:
                runtime["window_count"] = int(runtime["window_count"]) + 1
            return True, wait_seconds, ""

    def _provider_runtime_bucket(self, provider_name: str) -> dict[str, Any]:
        if provider_name not in self._provider_runtime:
            self._provider_runtime[provider_name] = {
                "window_start_ts": 0.0,
                "window_count": 0,
                "last_request_ts": 0.0,
            }
        return self._provider_runtime[provider_name]

    @staticmethod
    def _load_provider_rate_limit_from_env() -> dict[str, int]:
        return {
            "per_minute": max(1, _env_int("DATA_PROVIDER_RATE_LIMIT_PER_MINUTE", 120)),
            "min_interval_ms": max(0, _env_int("DATA_PROVIDER_MIN_INTERVAL_MS", 120)),
            "max_wait_ms": max(0, _env_int("DATA_PROVIDER_MAX_WAIT_MS", 400)),
        }

    @staticmethod
    def _load_retry_policy_from_env() -> dict[str, float]:
        return {
            "max_retries": max(0, _env_int("DATA_PROVIDER_BACKOFF_RETRIES", 2)),
            "base_ms": max(0, _env_int("DATA_PROVIDER_BACKOFF_BASE_MS", 80)),
            "factor": max(1.0, _env_float("DATA_PROVIDER_BACKOFF_FACTOR", 2.0)),
            "max_ms": max(1, _env_int("DATA_PROVIDER_BACKOFF_MAX_MS", 1000)),
        }

    @staticmethod
    def _load_quality_thresholds_from_env() -> dict[str, float]:
        return {
            "error_warn": _env_float("DATA_QUALITY_ERROR_WARN", 0.15),
            "error_block": _env_float("DATA_QUALITY_ERROR_BLOCK", 0.4),
            "empty_warn": _env_float("DATA_QUALITY_EMPTY_WARN", 0.3),
            "empty_block": _env_float("DATA_QUALITY_EMPTY_BLOCK", 0.7),
            "retry_warn": _env_float("DATA_QUALITY_RETRY_WARN", 0.2),
            "retry_block": _env_float("DATA_QUALITY_RETRY_BLOCK", 0.6),
            "rate_limited_warn": _env_float("DATA_QUALITY_RATE_LIMIT_WARN", 0.2),
            "rate_limited_block": _env_float("DATA_QUALITY_RATE_LIMIT_BLOCK", 0.5),
            "stale_warn_days": _env_int("DATA_QUALITY_STALE_WARN_DAYS", 3),
            "stale_block_days": _env_int("DATA_QUALITY_STALE_BLOCK_DAYS", 7),
            "provider_error_warn": _env_float("DATA_QUALITY_PROVIDER_ERROR_WARN", 0.5),
            "provider_error_block": _env_float("DATA_QUALITY_PROVIDER_ERROR_BLOCK", 0.9),
            "provider_min_requests": _env_int("DATA_QUALITY_PROVIDER_MIN_REQUESTS", 3),
        }

    def _compute_backoff_seconds(self, attempt: int) -> float:
        base_ms = float(self._retry_policy["base_ms"])
        factor = float(self._retry_policy["factor"])
        max_ms = float(self._retry_policy["max_ms"])
        if base_ms <= 0:
            return 0.0
        delay_ms = min(base_ms * (factor ** max(0, int(attempt))), max_ms)
        return max(0.0, delay_ms / 1000.0)

    def _provider_bucket(self, provider_name: str) -> dict[str, Any]:
        providers = self._metrics["providers"]
        if provider_name not in providers:
            providers[provider_name] = {
                "requests": 0,
                "success": 0,
                "failure": 0,
                "empty": 0,
                "fallback_success": 0,
                "retries": 0,
                "retry_success": 0,
                "rate_limited": 0,
                "last_error_code": "",
                "last_error": "",
                "last_success_ts": 0.0,
                "last_failure_ts": 0.0,
                "last_latency_ms": 0.0,
                "last_rate_limit_reason": "",
                "throttle_sleep_ms": 0.0,
                "backoff_sleep_ms": 0.0,
                "enabled": self._enabled.get(provider_name, True),
                "priority": self._priorities.get(provider_name, 100),
            }
        return providers[provider_name]

    def _mark_cache_decode_error(self, code: str, message: str) -> None:
        with self._lock:
            self._metrics["cache_decode_errors"] = int(self._metrics.get("cache_decode_errors", 0)) + 1
            self._metrics["cache_last_error_code"] = str(code or "CACHE_DECODE_ERROR")
            self._metrics["cache_last_error"] = str(message or "")[:300]

    def _build_quality_snapshot(
        self,
        *,
        error_rate: float,
        empty_rate: float,
        retry_rate: float,
        rate_limited_rate: float,
        providers: dict[str, dict[str, Any]],
        kline_last_age_days: int | None,
    ) -> dict[str, Any]:
        thresholds = dict(self._quality_thresholds)
        enabled_providers = [item for item in providers.values() if bool(item.get("enabled", True))]
        if not enabled_providers:
            return {
                "alert_level": "none",
                "action": "record",
                "code": "DATAFLOW_UNAVAILABLE",
                "thresholds": thresholds,
                "triggered_rules": [],
            }

        triggered_rules: list[dict[str, Any]] = []
        level = "none"

        def _trigger(rule_name: str, metric_name: str, value: float, warn: float, block: float, rule_level: str):
            nonlocal level
            triggered_rules.append(
                {
                    "rule": rule_name,
                    "metric": metric_name,
                    "value": round(float(value), 4),
                    "warn_threshold": warn,
                    "block_threshold": block,
                    "level": rule_level,
                }
            )
            level = _max_level(level, rule_level)

        if error_rate >= thresholds["error_block"]:
            _trigger(
                "overall_error_rate",
                "error_rate",
                error_rate,
                thresholds["error_warn"],
                thresholds["error_block"],
                "critical",
            )
        elif error_rate >= thresholds["error_warn"]:
            _trigger(
                "overall_error_rate",
                "error_rate",
                error_rate,
                thresholds["error_warn"],
                thresholds["error_block"],
                "warn",
            )

        if empty_rate >= thresholds["empty_block"]:
            _trigger(
                "overall_empty_rate",
                "empty_rate",
                empty_rate,
                thresholds["empty_warn"],
                thresholds["empty_block"],
                "critical",
            )
        elif empty_rate >= thresholds["empty_warn"]:
            _trigger(
                "overall_empty_rate",
                "empty_rate",
                empty_rate,
                thresholds["empty_warn"],
                thresholds["empty_block"],
                "warn",
            )

        if retry_rate >= thresholds["retry_block"]:
            _trigger(
                "overall_retry_rate",
                "retry_rate",
                retry_rate,
                thresholds["retry_warn"],
                thresholds["retry_block"],
                "critical",
            )
        elif retry_rate >= thresholds["retry_warn"]:
            _trigger(
                "overall_retry_rate",
                "retry_rate",
                retry_rate,
                thresholds["retry_warn"],
                thresholds["retry_block"],
                "warn",
            )

        if rate_limited_rate >= thresholds["rate_limited_block"]:
            _trigger(
                "overall_rate_limited_rate",
                "rate_limited_rate",
                rate_limited_rate,
                thresholds["rate_limited_warn"],
                thresholds["rate_limited_block"],
                "critical",
            )
        elif rate_limited_rate >= thresholds["rate_limited_warn"]:
            _trigger(
                "overall_rate_limited_rate",
                "rate_limited_rate",
                rate_limited_rate,
                thresholds["rate_limited_warn"],
                thresholds["rate_limited_block"],
                "warn",
            )

        if kline_last_age_days is not None:
            stale_value = float(kline_last_age_days)
            if stale_value >= thresholds["stale_block_days"]:
                _trigger(
                    "kline_freshness",
                    "kline_last_age_days",
                    stale_value,
                    float(thresholds["stale_warn_days"]),
                    float(thresholds["stale_block_days"]),
                    "critical",
                )
            elif stale_value >= thresholds["stale_warn_days"]:
                _trigger(
                    "kline_freshness",
                    "kline_last_age_days",
                    stale_value,
                    float(thresholds["stale_warn_days"]),
                    float(thresholds["stale_block_days"]),
                    "warn",
                )

        min_provider_requests = int(thresholds["provider_min_requests"])
        for provider_name, provider_metrics in providers.items():
            if not provider_metrics.get("enabled", True):
                continue
            requests = int(provider_metrics.get("requests", 0))
            if requests < min_provider_requests:
                continue

            provider_error_rate = float(provider_metrics.get("error_rate", 0.0))
            if provider_error_rate >= thresholds["provider_error_block"]:
                _trigger(
                    f"provider_health:{provider_name}",
                    "provider_error_rate",
                    provider_error_rate,
                    thresholds["provider_error_warn"],
                    thresholds["provider_error_block"],
                    "critical",
                )
            elif provider_error_rate >= thresholds["provider_error_warn"]:
                _trigger(
                    f"provider_health:{provider_name}",
                    "provider_error_rate",
                    provider_error_rate,
                    thresholds["provider_error_warn"],
                    thresholds["provider_error_block"],
                    "warn",
                )

        action = "block" if level == "critical" else "record"
        code = "DATA_QUALITY_BLOCK" if level == "critical" else "DATA_QUALITY_WARN" if level == "warn" else "DATA_QUALITY_OK"
        return {
            "alert_level": level,
            "action": action,
            "code": code,
            "thresholds": thresholds,
            "triggered_rules": triggered_rules,
        }

    def _register_quality_event(self, quality: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        level = str(quality.get("alert_level", "none"))
        code = str(quality.get("code", ""))
        action = str(quality.get("action", "record"))
        rule_names = sorted(str(item.get("rule", "")) for item in quality.get("triggered_rules", []) if isinstance(item, dict))
        signature = f"{level}|{code}|{','.join(rule_names)}"

        event: dict[str, Any] = {
            "event_id": "",
            "signature": signature,
            "timestamp": now,
            "level": level,
            "code": code,
            "action": action,
            "triggered_rules": rule_names,
            "new_event": False,
        }
        quality["event_id"] = ""
        quality["event_signature"] = signature
        quality["feedback_metrics"] = self._build_quality_feedback_metrics_locked()

        if level not in {"warn", "critical"}:
            self._quality_last_signature = signature
            self._quality_last_event_id = ""
            self._quality_last_event_ts = now
            return event

        # Suppress repeated events within 30s for same signature.
        if signature == self._quality_last_signature and (now - self._quality_last_event_ts) <= 30.0:
            event_id = self._quality_last_event_id
        else:
            self._quality_event_seq += 1
            event_id = f"dq-{int(now * 1000)}-{self._quality_event_seq}"
            event["new_event"] = True
            self._quality_event_history.append(
                {
                    "event_id": event_id,
                    "label": "alert",
                    "source": "runtime",
                    "note": "",
                    "timestamp": now,
                    "level": level,
                    "code": code,
                    "action": action,
                    "triggered_rules": rule_names,
                }
            )
            if len(self._quality_event_history) > self._quality_event_history_limit:
                self._quality_event_history = self._quality_event_history[-self._quality_event_history_limit :]

        self._quality_last_signature = signature
        self._quality_last_event_id = event_id
        self._quality_last_event_ts = now
        quality["event_id"] = event_id
        event["event_id"] = event_id
        return event

    def _build_quality_feedback_metrics_locked(self) -> dict[str, Any]:
        tp = max(0, int(self._quality_feedback.get("true_positive", 0)))
        fp = max(0, int(self._quality_feedback.get("false_positive", 0)))
        fn = max(0, int(self._quality_feedback.get("false_negative", 0)))
        alert_feedback_total = tp + fp
        precision = (tp / alert_feedback_total) if alert_feedback_total else 0.0
        false_positive_rate = (fp / alert_feedback_total) if alert_feedback_total else 0.0
        miss_denominator = tp + fn
        miss_rate = (fn / miss_denominator) if miss_denominator else 0.0
        return {
            "true_positive": tp,
            "false_positive": fp,
            "false_negative": fn,
            "feedback_total": int(self._quality_feedback.get("events_total", 0)),
            "precision": round(precision, 6),
            "false_positive_rate": round(false_positive_rate, 6),
            "miss_rate": round(miss_rate, 6),
            "updated_at": float(self._quality_feedback.get("updated_at", 0.0)),
        }

    def _build_tuning_snapshot(
        self,
        *,
        error_rate: float,
        retry_rate: float,
        rate_limited_rate: float,
        quality: dict[str, Any],
    ) -> dict[str, Any]:
        thresholds = self._quality_thresholds
        suggestions: list[dict[str, Any]] = []
        suggested_env: dict[str, str] = {}
        action = "none"

        def _set_action(level: str) -> None:
            nonlocal action
            rank = {"none": 0, "monitor": 1, "tune": 2, "urgent_tune": 3}
            if rank.get(level, 0) >= rank.get(action, 0):
                action = level

        if rate_limited_rate >= thresholds["rate_limited_warn"]:
            _set_action("tune")
            current_wait_ms = int(self._provider_rate_limit["max_wait_ms"])
            target_wait_ms = max(current_wait_ms, 800)
            suggested_env["DATA_PROVIDER_MAX_WAIT_MS"] = str(target_wait_ms)
            if rate_limited_rate >= thresholds["rate_limited_block"]:
                _set_action("urgent_tune")
                current_limit = int(self._provider_rate_limit["per_minute"])
                suggested_env["DATA_PROVIDER_RATE_LIMIT_PER_MINUTE"] = str(max(1, int(current_limit * 1.3)))
            suggestions.append(
                {
                    "metric": "rate_limited_rate",
                    "current_value": round(rate_limited_rate, 4),
                    "warn_threshold": thresholds["rate_limited_warn"],
                    "block_threshold": thresholds["rate_limited_block"],
                    "message": "回源请求被限流比例偏高，建议提高允许等待窗口并核查请求突发。",
                }
            )

        if retry_rate >= thresholds["retry_warn"]:
            _set_action("tune")
            current_retries = int(self._retry_policy["max_retries"])
            current_base_ms = int(self._retry_policy["base_ms"])
            suggested_env["DATA_PROVIDER_BACKOFF_RETRIES"] = str(max(2, current_retries))
            suggested_env["DATA_PROVIDER_BACKOFF_BASE_MS"] = str(max(80, current_base_ms))
            if retry_rate >= thresholds["retry_block"]:
                _set_action("urgent_tune")
                suggested_env["DATA_PROVIDER_BACKOFF_RETRIES"] = str(max(3, current_retries))
                suggested_env["DATA_PROVIDER_BACKOFF_BASE_MS"] = str(max(120, current_base_ms))
            suggestions.append(
                {
                    "metric": "retry_rate",
                    "current_value": round(retry_rate, 4),
                    "warn_threshold": thresholds["retry_warn"],
                    "block_threshold": thresholds["retry_block"],
                    "message": "回源重试比例偏高，建议提高退避重试配置并排查上游稳定性。",
                }
            )

        if error_rate >= thresholds["error_warn"]:
            _set_action("tune")
            current_factor = float(self._retry_policy["factor"])
            suggested_env["DATA_PROVIDER_BACKOFF_FACTOR"] = f"{max(2.0, current_factor):.2f}"
            if error_rate >= thresholds["error_block"]:
                _set_action("urgent_tune")
                suggested_env["DATA_PROVIDER_BACKOFF_FACTOR"] = f"{max(2.5, current_factor):.2f}"
            suggestions.append(
                {
                    "metric": "error_rate",
                    "current_value": round(error_rate, 4),
                    "warn_threshold": thresholds["error_warn"],
                    "block_threshold": thresholds["error_block"],
                    "message": "数据源错误率偏高，建议加大退避因子并切换/降级主数据源。",
                }
            )

        quality_level = str(quality.get("alert_level", "none"))
        if quality_level == "warn":
            _set_action("monitor" if action == "none" else action)
        if quality_level == "critical":
            _set_action("urgent_tune")

        return {
            "action": action,
            "quality_alert_level": quality_level,
            "suggestions": suggestions,
            "suggested_env": suggested_env,
            "observed": {
                "error_rate": round(error_rate, 4),
                "retry_rate": round(retry_rate, 4),
                "rate_limited_rate": round(rate_limited_rate, 4),
            },
        }

    @staticmethod
    def _json_safe(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, (datetime, date, pd.Timestamp)):
            return value.isoformat()
        item = getattr(value, "item", None)
        if callable(item):
            try:
                value = item()
            except Exception:  # noqa: BLE001
                return str(value)
        try:
            if pd.isna(value):
                return None
        except Exception:  # noqa: BLE001
            pass
        return value

    @staticmethod
    def _normalize_feedback_label(label: str) -> str:
        raw = str(label or "").strip().lower()
        mapping = {
            "tp": "true_positive",
            "true_positive": "true_positive",
            "hit": "true_positive",
            "fp": "false_positive",
            "false_positive": "false_positive",
            "false_alarm": "false_positive",
            "fn": "false_negative",
            "false_negative": "false_negative",
            "miss": "false_negative",
        }
        return mapping.get(raw, "")


class AkShareDataSourceAdapter(BaseDataSource):
    """Adapter to plug existing AkShareProvider into DataSourceManager."""

    def __init__(self):
        from src.dataflows.providers.akshare_provider import AkShareProvider

        self._provider = AkShareProvider()

    def get_kline(self, ticker: str, start_date: str, end_date: str, timeframe: str = "D") -> pd.DataFrame:
        if not PANDAS_AVAILABLE:
            return pd.DataFrame()

        # The upstream provider currently exposes limit-based API.
        limit = 400
        parsed_start = _parse_date(start_date)
        parsed_end = _parse_date(end_date)
        if parsed_start and parsed_end and parsed_end >= parsed_start:
            days = max(60, (parsed_end - parsed_start).days + 10)
            limit = min(days, 2000)

        df = self._provider.get_historical_kline(ticker, limit=limit)
        if not isinstance(df, pd.DataFrame) or df.empty:
            return pd.DataFrame()

        if "date" not in df.columns and not isinstance(df.index, pd.RangeIndex):
            df = df.reset_index().rename(columns={"index": "date"})

        if "date" in df.columns:
            date_series = pd.to_datetime(df["date"], errors="coerce")
            if parsed_start:
                df = df[date_series >= pd.Timestamp(parsed_start)]
            if parsed_end:
                df = df[date_series <= pd.Timestamp(parsed_end)]

        return df.reset_index(drop=True)

    def get_fundamentals(self, ticker: str) -> dict:
        # Reserved for future implementation.
        return {}

    def get_news(self, ticker: str, limit: int = 10) -> list[dict]:
        # Reserved for future implementation.
        return []

    def get_realtime_quote(self, ticker: str) -> dict[str, Any]:
        quote = self._provider.get_realtime_quote(ticker)
        return quote if isinstance(quote, dict) else {}

    def get_historical_kline(self, ticker: str, limit: int = 100) -> pd.DataFrame:
        if not PANDAS_AVAILABLE:
            return pd.DataFrame()
        df = self._provider.get_historical_kline(ticker, limit=limit)
        if isinstance(df, pd.DataFrame):
            return df
        return pd.DataFrame()

    def get_metrics(self) -> dict[str, Any]:
        if hasattr(self._provider, "get_metrics"):
            payload = self._provider.get_metrics()
            if isinstance(payload, dict):
                return payload
        return {}


class BaostockDataSourceAdapter(BaseDataSource):
    """Adapter to plug existing BaostockProvider into DataSourceManager."""

    def __init__(self):
        from src.dataflows.providers.baostock_provider import BaostockProvider

        self._provider = BaostockProvider()

    def get_kline(self, ticker: str, start_date: str, end_date: str, timeframe: str = "D") -> pd.DataFrame:
        if not PANDAS_AVAILABLE:
            return pd.DataFrame()

        limit = 400
        parsed_start = _parse_date(start_date)
        parsed_end = _parse_date(end_date)
        if parsed_start and parsed_end and parsed_end >= parsed_start:
            days = max(60, (parsed_end - parsed_start).days + 10)
            limit = min(days, 2000)

        df = self._provider.get_historical_kline(ticker, limit=limit)
        if not isinstance(df, pd.DataFrame) or df.empty:
            return pd.DataFrame()

        if "date" in df.columns:
            date_series = pd.to_datetime(df["date"], errors="coerce")
            if parsed_start:
                df = df[date_series >= pd.Timestamp(parsed_start)]
            if parsed_end:
                df = df[date_series <= pd.Timestamp(parsed_end)]

        return df.reset_index(drop=True)

    def get_fundamentals(self, ticker: str) -> dict:
        # Reserved for future implementation.
        return {}

    def get_news(self, ticker: str, limit: int = 10) -> list[dict]:
        # Reserved for future implementation.
        return []

    def get_realtime_quote(self, ticker: str) -> dict[str, Any]:
        quote = self._provider.get_realtime_quote(ticker)
        return quote if isinstance(quote, dict) else {}

    def get_historical_kline(self, ticker: str, limit: int = 100) -> pd.DataFrame:
        if not PANDAS_AVAILABLE:
            return pd.DataFrame()
        df = self._provider.get_historical_kline(ticker, limit=limit)
        if isinstance(df, pd.DataFrame):
            return df
        return pd.DataFrame()

    def get_metrics(self) -> dict[str, Any]:
        if hasattr(self._provider, "get_metrics"):
            payload = self._provider.get_metrics()
            if isinstance(payload, dict):
                return payload
        return {}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "")
    if raw == "":
        return float(default)
    try:
        return float(raw)
    except ValueError:
        return float(default)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "")
    if raw == "":
        return int(default)
    try:
        return int(raw)
    except ValueError:
        return int(default)


def _max_level(current: str, candidate: str) -> str:
    rank = {"none": 0, "warn": 1, "critical": 2}
    return candidate if rank.get(candidate, 0) >= rank.get(current, 0) else current


def _parse_date(raw: str) -> date | None:
    text = str(raw or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _is_env_true(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _bootstrap_default_sources(manager: DataSourceManager) -> None:
    if not _is_env_true("DATA_SOURCE_BOOTSTRAP_AKSHARE", default=True):
        logger.info("akshare data source bootstrap disabled by env")
    else:
        try:
            manager.register("akshare", AkShareDataSourceAdapter(), priority=10, is_primary=True, enabled=True)
        except Exception as exc:  # noqa: BLE001
            if "pandas" in str(exc).lower():
                logger.info("akshare data source bootstrap skipped: %s", exc)
            else:
                logger.warning("akshare data source bootstrap skipped: %s", exc)

    if not _is_env_true("DATA_SOURCE_BOOTSTRAP_BAOSTOCK", default=True):
        logger.info("baostock data source bootstrap disabled by env")
        return
    try:
        manager.register("baostock", BaostockDataSourceAdapter(), priority=20, is_primary=False, enabled=True)
    except Exception as exc:  # noqa: BLE001
        if "pandas" in str(exc).lower():
            logger.info("baostock data source bootstrap skipped: %s", exc)
            return
        logger.warning("baostock data source bootstrap skipped: %s", exc)


data_manager = DataSourceManager(cache=cache_manager)
_bootstrap_default_sources(data_manager)
