"""Service layer for unified dataflow manager access."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

try:
    import pandas as pd
except Exception:  # noqa: BLE001
    pd = None

from src.core.system_store import SystemStore
from src.dataflows.source_manager import DataSourceManager, data_manager


_PROVIDER_DISPLAY_NAME = {
    "akshare": "AkShare",
    "baostock": "BaoStock",
    "tushare": "Tushare",
}


class DataflowService:
    """Domain service for dataflow provider operations."""

    def __init__(self, manager: DataSourceManager | None = None):
        self._manager = manager or data_manager

    @staticmethod
    def _display_name(provider_name: str) -> str:
        key = str(provider_name or "").strip().lower()
        return _PROVIDER_DISPLAY_NAME.get(key, key.upper() if key else "Unknown")

    def get_metrics(self) -> dict[str, Any]:
        return self._manager.get_metrics()

    def reload_runtime_config_from_env(self) -> dict[str, Any]:
        return self._manager.reload_runtime_config_from_env()

    def record_quality_feedback(
        self,
        *,
        label: str,
        event_id: str = "",
        source: str = "api",
        note: str = "",
    ) -> dict[str, Any]:
        return self._manager.record_quality_feedback(label=label, event_id=event_id, source=source, note=note)

    def get_quality_feedback_metrics(self) -> dict[str, Any]:
        return self._manager.get_quality_feedback_metrics()

    def list_quality_events(self, limit: int = 50) -> list[dict[str, Any]]:
        return self._manager.list_quality_events(limit=limit)

    def list_provider_catalog(self) -> dict[str, Any]:
        metrics = self._manager.get_metrics()
        provider_order = metrics.get("provider_order", [])
        provider_metrics = metrics.get("providers", {})
        current_provider = str(metrics.get("current_provider") or self._manager.get_current_provider_name())

        providers: list[dict[str, Any]] = []
        if isinstance(provider_order, list):
            for item in provider_order:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name", "")).strip().lower()
                if not name:
                    continue
                metric_bucket = provider_metrics.get(name, {}) if isinstance(provider_metrics, dict) else {}
                providers.append(
                    {
                        "name": name,
                        "display_name": self._display_name(name),
                        "enabled": bool(item.get("enabled", False)),
                        "current": bool(item.get("current", False)),
                        "priority": int(item.get("priority", 100)),
                        "requests": int(metric_bucket.get("requests", 0)),
                        "success": int(metric_bucket.get("success", 0)),
                        "failure": int(metric_bucket.get("failure", 0)),
                        "empty": int(metric_bucket.get("empty", 0)),
                        "retry_success": int(metric_bucket.get("retry_success", 0)),
                        "rate_limited": int(metric_bucket.get("rate_limited", 0)),
                        "error_rate": float(metric_bucket.get("error_rate", 0.0)),
                        "empty_rate": float(metric_bucket.get("empty_rate", 0.0)),
                        "retry_rate": float(metric_bucket.get("retry_rate", 0.0)),
                        "rate_limited_rate": float(metric_bucket.get("rate_limited_rate", 0.0)),
                        "last_error_code": str(metric_bucket.get("last_error_code", "")),
                        "last_error": str(metric_bucket.get("last_error", "")),
                        "last_latency_ms": float(metric_bucket.get("last_latency_ms", 0.0)),
                        "last_success_ts": float(metric_bucket.get("last_success_ts", 0.0)),
                        "last_failure_ts": float(metric_bucket.get("last_failure_ts", 0.0)),
                    }
                )

        return {
            "current_provider": current_provider,
            "current_provider_display_name": self._display_name(current_provider),
            "providers": providers,
            "summary": metrics.get("summary", {}),
            "quality": metrics.get("quality", {}),
            "tuning": metrics.get("tuning", {}),
            "runtime_config": metrics.get("runtime_config", {}),
        }

    def switch_provider(
        self,
        *,
        provider_name: str,
        persist: bool = False,
        system_store: SystemStore | None = None,
    ) -> dict[str, Any]:
        normalized = str(provider_name or "").strip().lower()
        if not normalized:
            raise ValueError("provider is required")

        self._manager.use(normalized)
        persisted = False
        if persist and isinstance(system_store, SystemStore):
            system_store.set_setting("dataflow_active_provider", normalized)
            persisted = True

        payload = self.list_provider_catalog()
        payload.update(
            {
                "applied_provider": normalized,
                "applied_provider_display_name": self._display_name(normalized),
                "persisted": persisted,
            }
        )
        return payload

    def apply_persisted_provider(self, system_store: SystemStore | None) -> dict[str, Any]:
        if not isinstance(system_store, SystemStore):
            return {"applied": False, "reason": "system_store_not_available"}

        persisted = str(system_store.get_setting("dataflow_active_provider", "") or "").strip().lower()
        if not persisted:
            return {"applied": False, "reason": "no_persisted_provider"}

        self._manager.use(persisted)
        return {"applied": True, "provider": persisted}

    def get_provider_instance(self, name: str | None = None) -> Any:
        return self._manager.get_provider_instance(name)

    def get_realtime_quote(self, ticker: str) -> dict[str, Any]:
        provider = self._manager.get_provider_instance()
        if provider is not None and hasattr(provider, "get_realtime_quote"):
            quote = provider.get_realtime_quote(ticker)
            if isinstance(quote, dict):
                return quote

        end = datetime.now().date()
        start = end - timedelta(days=10)
        df = self._manager.get_kline(
            ticker=ticker,
            start_date=start.strftime("%Y-%m-%d"),
            end_date=end.strftime("%Y-%m-%d"),
            timeframe="D",
        )
        if pd is None or not isinstance(df, pd.DataFrame) or df.empty:
            return {}

        row = df.iloc[-1]
        close = float(row.get("close", 0.0) or 0.0)
        prev_close = float(df.iloc[-2].get("close", close) if len(df) > 1 else close)
        change_pct = ((close - prev_close) / prev_close * 100.0) if prev_close else 0.0
        amount = float(row.get("amount", 0.0) or 0.0)
        volume = float(row.get("volume", 0.0) or 0.0)
        turnover = float(row.get("turnover", amount) or amount)
        return {
            "ticker": ticker,
            "price": close,
            "change_pct": round(change_pct, 4),
            "amount": amount,
            "turnover": turnover,
            "volume": volume,
            "volume_chg": volume,
        }

    def get_market_kline(self, ticker: str, *, limit: int = 100) -> list[dict[str, Any]]:
        provider = self._manager.get_provider_instance()
        if provider is not None and hasattr(provider, "get_historical_kline"):
            payload = provider.get_historical_kline(ticker, limit=limit)
            if pd is not None and isinstance(payload, pd.DataFrame):
                if payload.empty:
                    return []
                return payload.to_dict(orient="records")
            if isinstance(payload, list):
                return [row for row in payload if isinstance(row, dict)]

        end = datetime.now().date()
        start = end - timedelta(days=max(120, int(limit) * 2))
        df = self._manager.get_kline(
            ticker=ticker,
            start_date=start.strftime("%Y-%m-%d"),
            end_date=end.strftime("%Y-%m-%d"),
            timeframe="D",
        )
        if pd is None or not isinstance(df, pd.DataFrame) or df.empty:
            return []
        if len(df) > int(limit):
            df = df.tail(int(limit))
        return df.to_dict(orient="records")
