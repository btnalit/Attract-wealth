"""Monitor domain service: encapsulates monitor router business logic."""
from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections import Counter
from typing import Any

from src.core.trading_ledger import TradingLedger
from src.dao.monitor_dao import MonitorDAO
from src.services.dataflow_service import DataflowService

logger = logging.getLogger(__name__)


class MonitorService:
    """Service layer for monitor APIs."""

    def __init__(self, trading_service: Any, monitor_dao: MonitorDAO | None = None):
        self._service = trading_service
        self._dataflow_service = DataflowService()
        self._dao = monitor_dao or MonitorDAO()

    @staticmethod
    def _to_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

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
        qmt_active = channel == "qmt"
        qmt_online = qmt_active and broker_connected
        qmt_status = "online" if qmt_online else ("offline" if qmt_active else "paused")
        now = time.time()
        return [
            {
                "name": "THS IPC",
                "status": "online" if ths_online else "offline",
                "latency_ms": 45.2 if ths_online else 0.0,
                "last_sync": now,
                "throughput": 120 if ths_online else 0,
            },
            {
                "name": "Simulator",
                "status": "online" if simulator_online else "offline",
                "latency_ms": 2.1 if simulator_online else 0.0,
                "last_sync": now,
                "throughput": 5000 if simulator_online else 0,
            },
            {
                "name": "miniQMT",
                "status": qmt_status,
                "latency_ms": 32.0 if qmt_online else 0.0,
                "last_sync": now if qmt_active else 0.0,
                "throughput": 60 if qmt_online else 0,
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

    def _build_wallet(self, snapshot: dict[str, Any], account_snapshot: dict[str, Any]) -> dict[str, Any]:
        balance = snapshot.get("balance", {}) if isinstance(snapshot.get("balance", {}), dict) else {}
        total_assets = self._to_float(balance.get("total_assets"), account_snapshot.get("balance", 0.0))
        available_cash = self._to_float(balance.get("available_cash"), account_snapshot.get("balance", 0.0))
        market_value = self._to_float(balance.get("market_value"), 0.0)
        daily_pnl = self._to_float(balance.get("daily_pnl"), 0.0)
        total_pnl = self._to_float(balance.get("total_pnl"), account_snapshot.get("total_pnl", 0.0))
        return {
            "total_assets": total_assets,
            "available_cash": available_cash,
            "market_value": market_value,
            "daily_pnl": daily_pnl,
            "total_pnl": total_pnl,
            "account_name": str(account_snapshot.get("name", "simulation")),
            "account_type": str(account_snapshot.get("type", "simulation")),
            "updated_at": self._to_float(account_snapshot.get("updated_at"), time.time()),
        }

    @staticmethod
    def _readiness_level(score: float) -> str:
        if score >= 80:
            return "stable"
        if score >= 60:
            return "attention"
        if score >= 40:
            return "degraded"
        return "critical"

    def _calc_readiness_score(
        self,
        channels: list[dict[str, Any]],
        risk: dict[str, Any],
        data_health: dict[str, Any],
    ) -> float:
        normalized_channels = channels if isinstance(channels, list) else []
        online_count = len([x for x in normalized_channels if str(x.get("status", "")).lower() == "online"])
        channel_ratio = online_count / max(len(normalized_channels), 1)

        drawdown_current = self._to_float(risk.get("max_drawdown_current"), 0.0)
        drawdown_threshold = max(self._to_float(risk.get("max_drawdown_threshold"), 0.05), 0.0001)
        position_current = self._to_float(risk.get("position_limit_current"), 0.0)
        position_threshold = max(self._to_float(risk.get("position_limit_threshold"), 0.30), 0.0001)
        drawdown_ratio = min(max(drawdown_current / drawdown_threshold, 0.0), 1.5)
        position_ratio = min(max(position_current / position_threshold, 0.0), 1.5)
        risk_pressure = min(max(max(drawdown_ratio, position_ratio), 0.0), 1.0)

        success_ratio = self._to_float(data_health.get("success_rate_ratio"), 0.0)
        success_ratio = min(max(success_ratio, 0.0), 1.0)
        paused_penalty = 20.0 if bool(risk.get("is_paused", False)) else 0.0

        score = channel_ratio * 45.0 + (1.0 - risk_pressure) * 30.0 + success_ratio * 25.0 - paused_penalty
        return round(min(max(score, 0.0), 100.0), 2)

    @staticmethod
    def _build_decision_summary(decisions: list[dict[str, Any]]) -> dict[str, Any]:
        if not decisions:
            return {
                "count": 0,
                "action_breakdown": {},
                "dominant_action": "HOLD",
                "avg_confidence": 0.0,
                "risk_pass_rate": 0.0,
            }

        action_counter = Counter(str(item.get("action", "HOLD")).upper() for item in decisions)
        dominant_action = action_counter.most_common(1)[0][0] if action_counter else "HOLD"
        avg_confidence = sum(float(item.get("confidence", 0.0) or 0.0) for item in decisions) / len(decisions)
        risk_pass_count = len([item for item in decisions if bool(item.get("risk_passed", False))])
        return {
            "count": len(decisions),
            "action_breakdown": dict(action_counter),
            "dominant_action": dominant_action,
            "avg_confidence": round(avg_confidence, 4),
            "risk_pass_rate": round(risk_pass_count / len(decisions), 4),
        }

    async def get_overview(self, *, switches: dict[str, bool]) -> dict[str, Any]:
        """Aggregate monitor overview payload for dashboard cockpit."""
        channels = self.get_system_status()
        data_health = self.get_data_health()
        risk = self.get_risk_metrics(switches=switches)

        snapshot: dict[str, Any] = {}
        if hasattr(self._service, "get_trade_snapshot"):
            try:
                maybe_snapshot = self._service.get_trade_snapshot(include_channel_raw=False)
                if inspect.isawaitable(maybe_snapshot):
                    maybe_snapshot = await maybe_snapshot
                snapshot = maybe_snapshot if isinstance(maybe_snapshot, dict) else {}
            except Exception as exc:  # noqa: BLE001
                logger.warning("monitor overview get_trade_snapshot failed: %s", exc)
                snapshot = {}

        account_snapshot = self._dao.get_latest_account_snapshot()
        positions = self._dao.list_top_positions(limit=8)
        recent_orders = self._dao.list_recent_direct_orders(limit=10)
        alerts = self._dao.list_recent_risk_alerts(limit=12)
        decisions = self._dao.list_recent_decision_actions(limit=20)
        decision_summary = self._build_decision_summary(decisions)

        readiness_score = self._calc_readiness_score(channels, risk, data_health)
        return {
            "generated_at": time.time(),
            "readiness_score": readiness_score,
            "readiness_level": self._readiness_level(readiness_score),
            "wallet": self._build_wallet(snapshot, account_snapshot),
            "risk": risk,
            "channels": channels,
            "data_health": data_health,
            "reconciliation_guard": snapshot.get("reconciliation_guard", {}),
            "positions": positions,
            "recent_orders": recent_orders,
            "alerts": alerts,
            "decision_summary": decision_summary,
            "counts": snapshot.get("counts", {}),
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

    async def get_market_kline(self, ticker: str, *, limit: int, interval: str = "daily") -> list[Any]:
        """Get historical K-line payload."""
        provider = self._get_data_provider()
        if provider is None:
            return []
        try:
            kline = await asyncio.to_thread(
                self._dataflow_service.get_market_kline,
                ticker,
                limit=limit,
                interval=interval,
            )
            return kline if isinstance(kline, list) else []
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to get kline for %s: %s", ticker, exc)
            return []
