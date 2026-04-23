"""Monitor domain service: encapsulates monitor router business logic."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from src.core.trading_ledger import TradingLedger
from src.services.dataflow_service import DataflowService

logger = logging.getLogger(__name__)


class MonitorService:
    """Service layer for monitor APIs."""

    def __init__(self, trading_service: Any):
        self._service = trading_service
        self._dataflow_service = DataflowService()

    @staticmethod
    def _is_ths_channel(channel: str) -> bool:
        return str(channel or "").strip().lower() in {"ths", "ths_auto", "ths_ipc"}

    def _is_broker_connected(self) -> bool:
        broker = getattr(self._service, "broker", None)
        return bool(getattr(broker, "is_connected", False))

    def _get_data_provider(self):
        """Get current provider from unified dataflow manager."""
        return self._dataflow_service.get_provider_instance()

    def get_system_status(self) -> list[dict[str, Any]]:
        """Return health status of trading channels."""
        channel = str(getattr(self._service, "channel", "")).strip().lower()
        broker_connected = self._is_broker_connected()

        ths_online = self._is_ths_channel(channel) and broker_connected
        simulator_online = channel == "simulation"
        now = time.time()
        return [
            {
                "name": "THS IPC",
                "status": "online" if ths_online else "offline",
                "latency_ms": 45.2 if ths_online else 0.0,
                "last_sync": now,
                "throughput": 120,
            },
            {
                "name": "Simulator",
                "status": "online" if simulator_online else "offline",
                "latency_ms": 2.1,
                "last_sync": now,
                "throughput": 5000,
            },
            {
                "name": "miniQMT",
                "status": "paused",
                "latency_ms": 0.0,
                "last_sync": 0.0,
                "throughput": 0,
            },
        ]

    def get_data_health(self) -> dict[str, Any]:
        """Return provider health payload with backward-compatible fields."""
        catalog = self._dataflow_service.list_provider_catalog()
        providers = catalog.get("providers", [])
        current_provider = str(catalog.get("current_provider", "")).strip().lower()
        current_bucket = {}
        if isinstance(providers, list):
            for item in providers:
                if not isinstance(item, dict):
                    continue
                if bool(item.get("current", False)) or str(item.get("name", "")).strip().lower() == current_provider:
                    current_bucket = item
                    break
        if not current_bucket and isinstance(providers, list) and providers:
            current_bucket = providers[0] if isinstance(providers[0], dict) else {}

        provider_runtime_metrics: dict[str, Any] = {}
        provider = self._dataflow_service.get_provider_instance(current_provider)
        if provider is not None and hasattr(provider, "get_metrics"):
            payload = provider.get_metrics()
            if isinstance(payload, dict):
                provider_runtime_metrics = payload

        requests = int(current_bucket.get("requests", 0))
        success = int(current_bucket.get("success", 0))
        success_rate_ratio = (success / requests) if requests > 0 else 0.0

        metrics: dict[str, Any] = {
            "provider": str(catalog.get("current_provider_display_name", current_provider or "Unknown")),
            "current_provider": current_provider,
            "current_provider_display_name": str(catalog.get("current_provider_display_name", "")),
            "providers": providers if isinstance(providers, list) else [],
            "total_requests": requests,
            "success_requests": success,
            "success_rate": success_rate_ratio,
            "avg_latency_ms": float(current_bucket.get("last_latency_ms", 0.0)),
            "last_fields": provider_runtime_metrics.get("last_fields", []),
            "uptime_seconds": int(provider_runtime_metrics.get("uptime_seconds", 0)),
            "status": "online" if current_provider else "provider_not_found",
            "summary": catalog.get("summary", {}),
            "quality": catalog.get("quality", {}),
            "tuning": catalog.get("tuning", {}),
            "runtime_config": catalog.get("runtime_config", {}),
        }

        last_fields = metrics.get("last_fields", [])
        if not isinstance(last_fields, list):
            last_fields = []
        recent_fields = provider_runtime_metrics.get("recent_fields", [])
        if not isinstance(recent_fields, list) or not recent_fields:
            recent_fields = list(last_fields)

        success_rate_raw = metrics.get("success_rate", 0.0)
        try:
            success_rate_raw = float(success_rate_raw)
        except (TypeError, ValueError):
            success_rate_raw = 0.0
        success_rate_pct = success_rate_raw * 100.0 if success_rate_raw <= 1.0 else success_rate_raw
        success_rate_ratio = success_rate_raw if success_rate_raw <= 1.0 else success_rate_raw / 100.0

        metrics["last_fields"] = last_fields
        metrics["recent_fields"] = recent_fields
        metrics["success_rate_pct"] = round(success_rate_pct, 2)
        metrics["success_rate_ratio"] = round(success_rate_ratio, 6)
        return metrics

    def get_risk_metrics(self, *, switches: dict[str, bool]) -> dict[str, Any]:
        """Return aggregated risk metrics for dashboard."""
        gate = self._service.risk_gate
        gate_metrics = gate.get_metrics() if hasattr(gate, "get_metrics") else {}
        recent_alerts = gate.get_recent_alerts(limit=200) if hasattr(gate, "get_recent_alerts") else []

        rule_hits = gate_metrics.get("rule_hits", {}) if isinstance(gate_metrics, dict) else {}
        pass_rate = float(gate_metrics.get("pass_rate", 1.0)) if isinstance(gate_metrics, dict) else 1.0

        max_drawdown_current = 0.0
        position_limit_current = 0.0
        for alert in recent_alerts:
            rule = str(alert.get("rule", "")).upper()
            context = alert.get("context", {}) if isinstance(alert.get("context"), dict) else {}
            value = float(context.get("value", 0.0) or 0.0)
            if rule == "DAILY_LOSS_LIMIT":
                max_drawdown_current = max(max_drawdown_current, value)
            elif rule == "POSITION_CONCENTRATION":
                position_limit_current = max(position_limit_current, value)

        return {
            "max_drawdown_current": max_drawdown_current,
            "max_drawdown_threshold": float(getattr(gate, "MAX_DAILY_LOSS_RATIO", 0.05)),
            "position_limit_current": position_limit_current,
            "position_limit_threshold": float(getattr(gate, "MAX_POSITION_CONCENTRATION", 0.30)),
            "trade_frequency_day": int(rule_hits.get("ORDER_FREQUENCY", 0)),
            "api_rate_limit_percent": round(max(0.0, min(1.0, 1.0 - pass_rate)) * 100.0, 2),
            "is_paused": bool(getattr(gate, "is_paused", False)),
            "switches": dict(switches),
        }

    def list_audit_logs(self, *, limit: int, offset: int) -> list[dict[str, Any]]:
        """Read audit logs from ledger storage."""
        rows = TradingLedger.list_ledger_entries(limit=limit + offset)
        sliced = rows[offset : offset + limit]
        logs: list[dict[str, Any]] = []
        for row in sliced:
            level = str(row.get("level", "")).upper()
            status = str(row.get("status", "")).lower()
            severity = "Low"
            if level in {"ERROR", "CRITICAL"} or status in {"error", "failed", "rejected"}:
                severity = "High"
            elif level in {"WARN", "WARNING"} or status in {"warning", "degraded"}:
                severity = "Medium"

            logs.append(
                {
                    "timestamp": float(row.get("timestamp", 0.0)),
                    "type": str(row.get("category", "SYSTEM")).title(),
                    "severity": severity,
                    "message": str(row.get("detail", "") or row.get("action", "")),
                    "payload": row.get("metadata", {}) if isinstance(row.get("metadata"), dict) else {},
                }
            )
        return logs

    def toggle_risk_switch(self, *, switch_name: str, enabled: bool, switches: dict[str, bool]) -> dict[str, Any]:
        """Apply risk switch changes and sync to RiskGate where needed."""
        updated_switches = dict(switches)
        updated_switches[switch_name] = enabled

        gate = self._service.risk_gate
        if switch_name in {"trading_pause", "global_pause"}:
            if hasattr(gate, "_trading_paused"):
                gate._trading_paused = enabled
            if hasattr(gate, "_paused"):
                gate._paused = enabled
            if hasattr(gate, "_pause_reason"):
                gate._pause_reason = "manual_toggle" if enabled else ""
        elif switch_name in {"daily_reset"} and enabled and hasattr(gate, "reset_daily"):
            gate.reset_daily()

        logger.info("Toggling risk switch %s to %s", switch_name, enabled)
        return {
            "name": switch_name,
            "enabled": enabled,
            "status": "updated",
            "switches": updated_switches,
            "risk_paused": bool(
                getattr(gate, "is_paused", False)
                or getattr(gate, "_trading_paused", False)
                or getattr(gate, "_paused", False)
            ),
        }

    async def get_market_quote(self, ticker: str) -> dict[str, Any]:
        """Get normalized realtime quote payload."""
        fallback = {
            "ticker": ticker,
            "price": 0.0,
            "change_pct": 0.0,
            "amount": 0.0,
            "turnover": 0.0,
            "volume_chg": 0.0,
            "volume": 0.0,
        }
        provider = self._get_data_provider()
        if provider is None:
            return {**fallback, "error": "data provider unavailable"}

        try:
            quote = await asyncio.to_thread(self._dataflow_service.get_realtime_quote, ticker)
            if not isinstance(quote, dict) or not quote:
                return fallback

            payload = dict(quote)
            payload.setdefault("ticker", ticker)
            if "turnover" not in payload and "amount" in payload:
                payload["turnover"] = payload.get("amount", 0.0)
            if "amount" not in payload and "turnover" in payload:
                payload["amount"] = payload.get("turnover", 0.0)
            if "volume" not in payload and "volume_chg" in payload:
                payload["volume"] = payload.get("volume_chg", 0.0)
            if "volume_chg" not in payload and "volume" in payload:
                payload["volume_chg"] = payload.get("volume", 0.0)
            return payload
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to get quote for %s: %s", ticker, exc)
            return {**fallback, "error": str(exc)}

    async def get_market_kline(self, ticker: str, *, limit: int) -> list[Any]:
        """Get historical K-line payload."""
        provider = self._get_data_provider()
        if provider is None:
            return []
        try:
            kline = await asyncio.to_thread(self._dataflow_service.get_market_kline, ticker, limit=limit)
            return kline if isinstance(kline, list) else []
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to get kline for %s: %s", ticker, exc)
            return []
