"""Monitor DAO: database aggregation queries for monitor domain."""
from __future__ import annotations

import json
from typing import Any, Callable

from src.core.storage import get_ledger_db, get_main_db


class MonitorDAO:
    """Read-only aggregation DAO for monitor/overview APIs."""

    def __init__(
        self,
        main_db_factory: Callable[[], Any] | None = None,
        ledger_db_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._main_db_factory = main_db_factory or get_main_db
        self._ledger_db_factory = ledger_db_factory or get_ledger_db

    @staticmethod
    def _to_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _to_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _loads(raw: Any) -> dict[str, Any]:
        if not raw:
            return {}
        if isinstance(raw, dict):
            return dict(raw)
        try:
            payload = json.loads(raw)
        except Exception:  # noqa: BLE001
            return {}
        return payload if isinstance(payload, dict) else {}

    def get_latest_account_snapshot(self) -> dict[str, Any]:
        """Read latest account snapshot from main DB."""
        with self._main_db_factory() as db:
            row = db.execute(
                """
                SELECT id, name, type, balance, total_pnl, created_at, updated_at
                FROM accounts
                ORDER BY updated_at DESC, created_at DESC
                LIMIT 1
                """
            ).fetchone()

        if not row:
            return {
                "id": "",
                "name": "simulation",
                "type": "simulation",
                "balance": 0.0,
                "total_pnl": 0.0,
                "created_at": 0.0,
                "updated_at": 0.0,
            }

        return {
            "id": str(row[0] or ""),
            "name": str(row[1] or ""),
            "type": str(row[2] or "simulation"),
            "balance": self._to_float(row[3], 0.0),
            "total_pnl": self._to_float(row[4], 0.0),
            "created_at": self._to_float(row[5], 0.0),
            "updated_at": self._to_float(row[6], 0.0),
        }

    def list_top_positions(self, *, limit: int = 6) -> list[dict[str, Any]]:
        """Return top positions sorted by market value."""
        target_limit = max(1, int(limit))
        with self._main_db_factory() as db:
            rows = db.execute(
                """
                SELECT ticker, market, quantity, available, avg_cost, current_price, unrealized_pnl, market_value, updated_at
                FROM positions
                ORDER BY market_value DESC, updated_at DESC
                LIMIT ?
                """,
                (target_limit,),
            ).fetchall()

        payload: list[dict[str, Any]] = []
        for row in rows:
            payload.append(
                {
                    "ticker": str(row[0] or ""),
                    "market": str(row[1] or "CN"),
                    "quantity": self._to_int(row[2], 0),
                    "available": self._to_int(row[3], 0),
                    "avg_cost": self._to_float(row[4], 0.0),
                    "current_price": self._to_float(row[5], 0.0),
                    "unrealized_pnl": self._to_float(row[6], 0.0),
                    "market_value": self._to_float(row[7], 0.0),
                    "updated_at": self._to_float(row[8], 0.0),
                }
            )
        return payload

    def list_recent_direct_orders(self, *, limit: int = 10) -> list[dict[str, Any]]:
        """Return recent direct order traces from main DB."""
        target_limit = max(1, int(limit))
        with self._main_db_factory() as db:
            rows = db.execute(
                """
                SELECT request_id, idempotency_key, channel, ticker, side, quantity, price, order_type,
                       status, error_code, error_message, response_payload, created_at, updated_at
                FROM direct_order_requests
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (target_limit,),
            ).fetchall()

        payload: list[dict[str, Any]] = []
        for row in rows:
            response_payload = self._loads(row[11])
            payload.append(
                {
                    "request_id": str(row[0] or ""),
                    "idempotency_key": str(row[1] or ""),
                    "channel": str(row[2] or ""),
                    "ticker": str(row[3] or ""),
                    "side": str(row[4] or "").upper(),
                    "quantity": self._to_int(row[5], 0),
                    "price": self._to_float(row[6], 0.0),
                    "order_type": str(row[7] or "limit"),
                    "status": str(row[8] or "").upper(),
                    "error_code": str(row[9] or ""),
                    "error_message": str(row[10] or ""),
                    "trace_id": str(response_payload.get("trace", {}).get("trace_id", "")),
                    "updated_at": self._to_float(row[13], 0.0),
                    "created_at": self._to_float(row[12], 0.0),
                }
            )
        return payload

    def list_recent_risk_alerts(self, *, limit: int = 12) -> list[dict[str, Any]]:
        """Return recent risk/system alerts from ledger DB."""
        target_limit = max(1, int(limit))
        raw_limit = min(2000, max(target_limit * 6, 100))
        with self._ledger_db_factory() as db:
            rows = db.execute(
                """
                SELECT timestamp, level, category, action, detail, status, metadata
                FROM ledger_entries
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (raw_limit,),
            ).fetchall()

        payload: list[dict[str, Any]] = []
        for row in rows:
            level = str(row[1] or "").upper()
            category = str(row[2] or "").upper()
            status = str(row[5] or "").lower()
            is_alert = (
                category in {"RISK", "SYSTEM", "RECONCILIATION"}
                and (
                    level in {"ERROR", "CRITICAL", "WARN", "WARNING"}
                    or status in {"failed", "rejected", "degraded", "warning"}
                )
            )
            if not is_alert:
                continue

            severity = "low"
            if level in {"ERROR", "CRITICAL"} or status in {"failed", "rejected"}:
                severity = "high"
            elif level in {"WARN", "WARNING"} or status in {"warning", "degraded"}:
                severity = "medium"

            payload.append(
                {
                    "timestamp": self._to_float(row[0], 0.0),
                    "level": level or "INFO",
                    "category": category or "SYSTEM",
                    "action": str(row[3] or ""),
                    "detail": str(row[4] or ""),
                    "status": str(row[5] or ""),
                    "severity": severity,
                    "metadata": self._loads(row[6]),
                }
            )
            if len(payload) >= target_limit:
                break
        return payload

    def list_recent_decision_actions(self, *, limit: int = 20) -> list[dict[str, Any]]:
        """Return recent decision evidence action records."""
        target_limit = max(1, int(limit))
        with self._main_db_factory() as db:
            rows = db.execute(
                """
                SELECT timestamp, ticker, channel, decision, action, confidence, percentage, risk_passed, risk_reason
                FROM decision_evidence
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (target_limit,),
            ).fetchall()

        payload: list[dict[str, Any]] = []
        for row in rows:
            payload.append(
                {
                    "timestamp": self._to_float(row[0], 0.0),
                    "ticker": str(row[1] or ""),
                    "channel": str(row[2] or ""),
                    "decision": str(row[3] or "").upper(),
                    "action": str(row[4] or "").upper(),
                    "confidence": self._to_float(row[5], 0.0),
                    "percentage": self._to_float(row[6], 0.0),
                    "risk_passed": bool(self._to_int(row[7], 0)),
                    "risk_reason": str(row[8] or ""),
                }
            )
        return payload

