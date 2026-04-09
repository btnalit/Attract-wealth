"""
Trading ledger and audit persistence.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from typing import Any, Optional

from pydantic import BaseModel, Field

from src.core.storage import get_ledger_db, get_main_db

TERMINAL_STATUSES = {"filled", "cancelled", "rejected", "failed"}


class LedgerEntry(BaseModel):
    """Immutable audit trail entry."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = Field(default_factory=time.time)
    level: str = "INFO"
    category: str = "SYSTEM"  # TRADE/ANALYSIS/EVOLUTION/SYSTEM
    agent_id: Optional[str] = None
    action: str
    detail: str
    status: str = "success"
    metadata: dict[str, Any] = Field(default_factory=dict)


class TradeRecord(BaseModel):
    """Single trade record."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = Field(default_factory=time.time)
    ticker: str
    market: str = "CN"
    action: str  # BUY/SELL/HOLD
    price: Optional[float] = 0.0
    filled_price: Optional[float] = 0.0
    quantity: Optional[int] = 0
    filled_quantity: Optional[int] = 0
    amount: Optional[float] = 0.0
    pnl: Optional[float] = 0.0
    commission: Optional[float] = 0.0
    confidence: Optional[float] = None
    agent_id: Optional[str] = None
    session_id: Optional[str] = None
    channel: str = "simulation"
    status: str = "pending"
    metadata: dict[str, Any] = Field(default_factory=dict)


class AnalysisReport(BaseModel):
    """Structured analysis record."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = Field(default_factory=time.time)
    ticker: str
    report_type: str  # fundamental/technical/news/sentiment
    agent_id: Optional[str] = None
    content: str
    decision: str = "HOLD"
    confidence: Optional[float] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TradingLedger:
    """Persistence access layer for trading/audit records."""

    @staticmethod
    def record_entry(entry: LedgerEntry) -> None:
        with get_ledger_db() as db:
            db.execute(
                """
                INSERT INTO ledger_entries
                (id, timestamp, level, category, agent_id, action, detail, status, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.id,
                    entry.timestamp,
                    entry.level,
                    entry.category,
                    entry.agent_id,
                    entry.action,
                    entry.detail,
                    entry.status,
                    json.dumps(entry.metadata, ensure_ascii=False),
                ),
            )

    @staticmethod
    def record_trade(trade: TradeRecord) -> bool:
        """
        Idempotent upsert of trade record.

        Returns:
            bool: True when record changed, False when idempotent no-op.
        """
        existing = TradingLedger.get_trade(trade.id)
        if existing and TradingLedger._is_same_trade(existing, trade):
            return False

        with get_main_db() as db:
            db.execute(
                """
                INSERT INTO trading_records
                (id, timestamp, ticker, market, action, price, filled_price, quantity,
                 filled_quantity, amount, pnl, commission, confidence, agent_id, session_id,
                 channel, status, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    timestamp = excluded.timestamp,
                    ticker = excluded.ticker,
                    market = excluded.market,
                    action = excluded.action,
                    price = excluded.price,
                    filled_price = excluded.filled_price,
                    quantity = excluded.quantity,
                    filled_quantity = excluded.filled_quantity,
                    amount = excluded.amount,
                    pnl = excluded.pnl,
                    commission = excluded.commission,
                    confidence = excluded.confidence,
                    agent_id = excluded.agent_id,
                    session_id = excluded.session_id,
                    channel = excluded.channel,
                    status = excluded.status,
                    metadata = excluded.metadata
                """,
                (
                    trade.id,
                    trade.timestamp,
                    trade.ticker,
                    trade.market,
                    trade.action,
                    trade.price,
                    trade.filled_price,
                    trade.quantity,
                    trade.filled_quantity,
                    trade.amount,
                    trade.pnl,
                    trade.commission,
                    trade.confidence,
                    trade.agent_id,
                    trade.session_id,
                    trade.channel,
                    trade.status,
                    json.dumps(trade.metadata, ensure_ascii=False),
                ),
            )

        TradingLedger.record_entry(
            LedgerEntry(
                category="TRADE",
                level="INFO",
                agent_id=trade.agent_id,
                action="UPSERT_TRADE" if existing else trade.action,
                detail=f"{trade.action} {trade.ticker} {trade.quantity} shares",
                status=trade.status,
                metadata={"trade_id": trade.id, "channel": trade.channel},
            )
        )
        return True

    @staticmethod
    def record_analysis(report: AnalysisReport) -> None:
        with get_main_db() as db:
            db.execute(
                """
                INSERT INTO analysis_reports
                (id, timestamp, ticker, report_type, agent_id, content, decision, confidence, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report.id,
                    report.timestamp,
                    report.ticker,
                    report.report_type,
                    report.agent_id,
                    report.content,
                    report.decision,
                    report.confidence,
                    json.dumps(report.metadata, ensure_ascii=False),
                ),
            )

    @staticmethod
    def record_reconciliation(report: dict[str, Any]) -> None:
        with get_main_db() as db:
            db.execute(
                """
                INSERT INTO reconciliation_reports
                (id, timestamp, channel, status, issues_count, snapshot)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    time.time(),
                    str(report.get("channel", "")),
                    str(report.get("status", "unknown")),
                    int(report.get("issues_count", 0)),
                    json.dumps(report, ensure_ascii=False),
                ),
            )

    @staticmethod
    def record_decision_evidence(payload: dict[str, Any]) -> str:
        """Store one end-to-end decision evidence chain snapshot."""
        evidence_id = str(payload.get("id") or str(uuid.uuid4()))
        timestamp = float(payload.get("timestamp") or time.time())
        phase = str(payload.get("phase") or "analyze")
        session_id = str(payload.get("session_id") or "")
        ticker = str(payload.get("ticker") or "")
        channel = str(payload.get("channel") or "simulation")
        decision = str(payload.get("decision") or "HOLD")
        confidence = float(payload.get("confidence") or 0.0)
        action = str(payload.get("action") or "HOLD")
        percentage = float(payload.get("percentage") or 0.0)
        reason = str(payload.get("reason") or "")
        risk_check = payload.get("risk_check") or {}
        risk_passed = 1 if bool(risk_check.get("passed", True)) else 0
        risk_reason = str(risk_check.get("reason") or "")

        with get_main_db() as db:
            db.execute(
                """
                INSERT INTO decision_evidence
                (id, timestamp, phase, session_id, ticker, channel, decision, confidence, action, percentage, reason,
                 risk_passed, risk_reason, evidence_payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence_id,
                    timestamp,
                    phase,
                    session_id,
                    ticker,
                    channel,
                    decision,
                    confidence,
                    action,
                    percentage,
                    reason,
                    risk_passed,
                    risk_reason,
                    json.dumps(payload, ensure_ascii=False, default=TradingLedger._json_default),
                ),
            )
        return evidence_id

    @staticmethod
    def list_decision_evidence(
        *,
        limit: int = 50,
        ticker: str = "",
        session_id: str = "",
        phase: str = "",
        request_id: str = "",
        degraded_only: bool = False,
    ) -> list[dict[str, Any]]:
        clauses = []
        params: list[Any] = []
        if ticker:
            clauses.append("ticker = ?")
            params.append(ticker)
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if phase:
            clauses.append("phase = ?")
            params.append(phase)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        target_limit = max(1, int(limit))
        raw_limit = target_limit
        if request_id or degraded_only:
            raw_limit = min(2000, max(target_limit * 6, 200))
        sql = (
            "SELECT id, timestamp, phase, session_id, ticker, channel, decision, confidence, action, percentage, "
            "reason, risk_passed, risk_reason, evidence_payload "
            f"FROM decision_evidence {where_sql} ORDER BY timestamp DESC LIMIT ?"
        )
        params.append(raw_limit)
        with get_main_db() as db:
            rows = db.execute(sql, tuple(params)).fetchall()

        records: list[dict[str, Any]] = []
        for row in rows:
            payload = TradingLedger._json_loads(row[13])
            payload_trace = payload.get("trace", {}) if isinstance(payload, dict) else {}
            payload_request_id = ""
            if isinstance(payload, dict):
                payload_request_id = str(
                    payload.get("request_id")
                    or payload_trace.get("request_id", "")
                    or ""
                )
            if request_id:
                if request_id != payload_request_id and request_id != str(row[3] or ""):
                    continue

            is_degraded = False
            if isinstance(payload, dict):
                degrade_flags = payload.get("degrade_flags", [])
                degrade_policy = payload.get("degrade_policy", {})
                matched_rules = (
                    degrade_policy.get("matched_rules", [])
                    if isinstance(degrade_policy, dict)
                    else []
                )
                is_degraded = bool(degrade_flags or matched_rules)
            if degraded_only and not is_degraded:
                continue

            records.append(
                {
                    "id": row[0],
                    "timestamp": float(row[1] or 0.0),
                    "phase": str(row[2] or ""),
                    "session_id": str(row[3] or ""),
                    "request_id": payload_request_id,
                    "trace_id": str(payload_trace.get("trace_id", "")) if isinstance(payload_trace, dict) else "",
                    "ticker": str(row[4] or ""),
                    "channel": str(row[5] or ""),
                    "decision": str(row[6] or ""),
                    "confidence": float(row[7] or 0.0),
                    "action": str(row[8] or ""),
                    "percentage": float(row[9] or 0.0),
                    "reason": str(row[10] or ""),
                    "risk_passed": bool(int(row[11] or 0)),
                    "risk_reason": str(row[12] or ""),
                    "degraded": is_degraded,
                    "payload": payload,
                }
            )
            if len(records) >= target_limit:
                break
        return records

    @staticmethod
    def record_llm_usage(payload: dict[str, Any]) -> str:
        """Persist one LLM cost and token usage event."""
        usage_id = str(payload.get("id") or str(uuid.uuid4()))
        with get_main_db() as db:
            db.execute(
                """
                INSERT INTO llm_costs
                (id, timestamp, provider, model, input_tokens, output_tokens, cost_usd, agent_id, session_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    usage_id,
                    float(payload.get("timestamp") or time.time()),
                    str(payload.get("provider") or ""),
                    str(payload.get("model") or ""),
                    int(payload.get("input_tokens") or 0),
                    int(payload.get("output_tokens") or 0),
                    float(payload.get("cost_usd") or 0.0),
                    str(payload.get("agent_id") or ""),
                    str(payload.get("session_id") or ""),
                ),
            )
        return usage_id

    @staticmethod
    def get_llm_usage_summary(
        *,
        hours: int = 24,
        agent_id: str = "",
        session_id: str = "",
    ) -> dict[str, Any]:
        since = time.time() - max(1, int(hours)) * 3600
        clauses = ["timestamp >= ?"]
        params: list[Any] = [since]
        if agent_id:
            clauses.append("agent_id = ?")
            params.append(agent_id)
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        where_sql = " AND ".join(clauses)

        with get_main_db() as db:
            row = db.execute(
                f"""
                SELECT
                    COUNT(1) AS call_count,
                    COALESCE(SUM(input_tokens), 0) AS input_tokens,
                    COALESCE(SUM(output_tokens), 0) AS output_tokens,
                    COALESCE(SUM(cost_usd), 0) AS cost_usd
                FROM llm_costs
                WHERE {where_sql}
                """,
                tuple(params),
            ).fetchone()

        call_count = int(row[0] or 0) if row else 0
        input_tokens = int(row[1] or 0) if row else 0
        output_tokens = int(row[2] or 0) if row else 0
        cost_usd = float(row[3] or 0.0) if row else 0.0
        avg_tokens = (input_tokens + output_tokens) / call_count if call_count else 0.0
        return {
            "window_hours": max(1, int(hours)),
            "call_count": call_count,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "cost_usd": round(cost_usd, 6),
            "avg_tokens_per_call": round(avg_tokens, 2),
            "agent_id": agent_id,
            "session_id": session_id,
        }

    @staticmethod
    def create_direct_order_request(
        *,
        request_id: str,
        idempotency_key: str,
        client_order_id: str,
        channel: str,
        ticker: str,
        side: str,
        quantity: int,
        price: float,
        order_type: str = "limit",
        response_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        with get_main_db() as db:
            existing = db.execute(
                """
                SELECT *
                FROM direct_order_requests
                WHERE idempotency_key = ?
                LIMIT 1
                """,
                (idempotency_key,),
            ).fetchone()
            if existing:
                return {"created": False, "record": TradingLedger._direct_order_row_to_dict(existing)}

            try:
                db.execute(
                    """
                    INSERT INTO direct_order_requests
                    (id, created_at, updated_at, request_id, idempotency_key, client_order_id,
                     channel, ticker, side, quantity, price, order_type, status, response_payload)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        now,
                        now,
                        request_id,
                        idempotency_key,
                        client_order_id,
                        channel,
                        ticker,
                        side.upper(),
                        int(quantity),
                        float(price),
                        order_type,
                        "received",
                        json.dumps(response_payload or {}, ensure_ascii=False, default=TradingLedger._json_default),
                    ),
                )
            except sqlite3.IntegrityError:
                existing = db.execute(
                    """
                    SELECT *
                    FROM direct_order_requests
                    WHERE idempotency_key = ?
                    LIMIT 1
                    """,
                    (idempotency_key,),
                ).fetchone()
                if existing:
                    return {"created": False, "record": TradingLedger._direct_order_row_to_dict(existing)}
                raise

            row = db.execute(
                """
                SELECT *
                FROM direct_order_requests
                WHERE idempotency_key = ?
                LIMIT 1
                """,
                (idempotency_key,),
            ).fetchone()
        return {"created": True, "record": TradingLedger._direct_order_row_to_dict(row) if row else {}}

    @staticmethod
    def finalize_direct_order_request(
        *,
        idempotency_key: str,
        status: str,
        local_order_id: str = "",
        broker_order_id: str = "",
        error_code: str = "",
        error_message: str = "",
        response_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        with get_main_db() as db:
            db.execute(
                """
                UPDATE direct_order_requests
                SET
                    updated_at = ?,
                    status = ?,
                    local_order_id = CASE WHEN ? <> '' THEN ? ELSE local_order_id END,
                    broker_order_id = CASE WHEN ? <> '' THEN ? ELSE broker_order_id END,
                    error_code = ?,
                    error_message = ?,
                    response_payload = ?
                WHERE idempotency_key = ?
                """,
                (
                    now,
                    str(status or "").lower(),
                    local_order_id,
                    local_order_id,
                    broker_order_id,
                    broker_order_id,
                    error_code or None,
                    error_message or None,
                    json.dumps(response_payload or {}, ensure_ascii=False, default=TradingLedger._json_default),
                    idempotency_key,
                ),
            )
            row = db.execute(
                """
                SELECT *
                FROM direct_order_requests
                WHERE idempotency_key = ?
                LIMIT 1
                """,
                (idempotency_key,),
            ).fetchone()
        return TradingLedger._direct_order_row_to_dict(row) if row else {}

    @staticmethod
    def get_direct_order_request(idempotency_key: str) -> Optional[dict[str, Any]]:
        with get_main_db() as db:
            row = db.execute(
                """
                SELECT *
                FROM direct_order_requests
                WHERE idempotency_key = ?
                LIMIT 1
                """,
                (idempotency_key,),
            ).fetchone()
        if not row:
            return None
        return TradingLedger._direct_order_row_to_dict(row)

    @staticmethod
    def get_direct_order_trace(
        *,
        idempotency_key: str = "",
        local_order_id: str = "",
        client_order_id: str = "",
        request_id: str = "",
        trace_id: str = "",
    ) -> Optional[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if idempotency_key:
            clauses.append("idempotency_key = ?")
            params.append(idempotency_key)
        elif local_order_id:
            clauses.append("local_order_id = ?")
            params.append(local_order_id)
        elif client_order_id:
            clauses.append("client_order_id = ?")
            params.append(client_order_id)
        elif request_id:
            clauses.append("request_id = ?")
            params.append(request_id)
        elif trace_id:
            with get_main_db() as db:
                rows = db.execute(
                    """
                    SELECT *
                    FROM direct_order_requests
                    ORDER BY updated_at DESC
                    LIMIT 500
                    """
                ).fetchall()
            for row in rows:
                payload = TradingLedger._json_loads(row[17])
                payload_trace = payload.get("trace", {}) if isinstance(payload, dict) else {}
                payload_trace_id = str(payload_trace.get("trace_id", "") or payload.get("trace_id", ""))
                if payload_trace_id == trace_id:
                    return TradingLedger._direct_order_row_to_dict(row)
            return None
        else:
            return None

        with get_main_db() as db:
            row = db.execute(
                f"""
                SELECT *
                FROM direct_order_requests
                WHERE {' AND '.join(clauses)}
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                tuple(params),
            ).fetchone()
        if not row:
            return None
        return TradingLedger._direct_order_row_to_dict(row)

    @staticmethod
    def list_ledger_entries(
        *,
        limit: int = 50,
        category: str = "",
        action: str = "",
        status: str = "",
        trace_id: str = "",
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if category:
            clauses.append("category = ?")
            params.append(category)
        if action:
            clauses.append("action = ?")
            params.append(action)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        raw_limit = min(2000, max(100, int(limit) * 6))

        with get_ledger_db() as db:
            rows = db.execute(
                f"""
                SELECT id, timestamp, level, category, agent_id, action, detail, status, metadata
                FROM ledger_entries
                {where_sql}
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (*params, raw_limit),
            ).fetchall()

        records: list[dict[str, Any]] = []
        for row in rows:
            metadata = TradingLedger._json_loads(row[8])
            if trace_id:
                payload_trace_id = str(metadata.get("trace_id", "")) if isinstance(metadata, dict) else ""
                if payload_trace_id != trace_id:
                    continue
            records.append(
                {
                    "id": str(row[0] or ""),
                    "timestamp": float(row[1] or 0.0),
                    "level": str(row[2] or ""),
                    "category": str(row[3] or ""),
                    "agent_id": str(row[4] or ""),
                    "action": str(row[5] or ""),
                    "detail": str(row[6] or ""),
                    "status": str(row[7] or ""),
                    "metadata": metadata if isinstance(metadata, dict) else {},
                }
            )
            if len(records) >= max(1, int(limit)):
                break
        return records

    @staticmethod
    def update_trade_status(
        trade_id: str,
        status: str,
        filled_price: float = 0.0,
        filled_quantity: int = 0,
    ) -> dict[str, Any]:
        """
        Update order status and fills with idempotent merge.

        Returns:
            dict: {"updated": bool, "reason": str, "status": str}
        """
        new_status = TradingLedger._normalize_status(status)

        with get_main_db() as db:
            row = db.execute(
                """
                SELECT status, filled_price, filled_quantity
                FROM trading_records
                WHERE id = ?
                """,
                (trade_id,),
            ).fetchone()
            if not row:
                return {"updated": False, "reason": "not_found", "status": new_status}

            old_status = TradingLedger._normalize_status(row[0])
            old_filled_price = float(row[1] or 0.0)
            old_filled_qty = int(row[2] or 0)
            merged_status = TradingLedger._merge_status(old_status, new_status)
            merged_filled_price = filled_price if filled_price > 0 else old_filled_price
            merged_filled_qty = max(old_filled_qty, int(filled_quantity or 0))

            if (
                merged_status == old_status
                and merged_filled_price == old_filled_price
                and merged_filled_qty == old_filled_qty
            ):
                return {"updated": False, "reason": "idempotent_no_change", "status": old_status}

            db.execute(
                """
                UPDATE trading_records
                SET status = ?, filled_price = ?, filled_quantity = ?
                WHERE id = ?
                """,
                (merged_status, merged_filled_price, merged_filled_qty, trade_id),
            )
            db.execute(
                """
                UPDATE direct_order_requests
                SET updated_at = ?, status = ?
                WHERE local_order_id = ?
                """,
                (time.time(), merged_status, trade_id),
            )

        TradingLedger.record_entry(
            LedgerEntry(
                category="TRADE",
                level="INFO",
                action="UPDATE_STATUS",
                detail=f"Trade {trade_id} status updated to {merged_status}",
                metadata={
                    "trade_id": trade_id,
                    "status": merged_status,
                    "filled_price": merged_filled_price,
                    "filled_quantity": merged_filled_qty,
                },
            )
        )
        return {"updated": True, "reason": "ok", "status": merged_status}

    @staticmethod
    def get_trade(trade_id: str) -> Optional[dict[str, Any]]:
        with get_main_db() as db:
            row = db.execute(
                """
                SELECT id, ticker, action, status, price, filled_price, quantity, filled_quantity, amount, commission, metadata
                FROM trading_records
                WHERE id = ?
                """,
                (trade_id,),
            ).fetchone()
            if not row:
                return None
            return {
                "id": row[0],
                "ticker": row[1],
                "action": row[2],
                "status": row[3],
                "price": float(row[4] or 0.0),
                "filled_price": float(row[5] or 0.0),
                "quantity": int(row[6] or 0),
                "filled_quantity": int(row[7] or 0),
                "amount": float(row[8] or 0.0),
                "commission": float(row[9] or 0.0),
                "metadata": TradingLedger._json_loads(row[10]),
            }

    @staticmethod
    def list_open_trade_ids() -> set[str]:
        with get_main_db() as db:
            rows = db.execute(
                """
                SELECT id
                FROM trading_records
                WHERE status IN ('pending', 'submitted', 'partial')
                """
            ).fetchall()
            return {str(row[0]) for row in rows}

    @staticmethod
    def build_portfolio_snapshot(initial_cash: float = 1_000_000.0, channel: str = "") -> dict[str, Any]:
        """Rebuild a cash/position snapshot from filled trades.

        When ``channel`` is provided, only that trading channel is included.
        """
        normalized_channel = str(channel or "").strip().lower()
        query = (
            "SELECT ticker, action, price, filled_price, quantity, filled_quantity, amount, commission "
            "FROM trading_records "
            "WHERE status IN ('filled', 'partial') "
        )
        params: list[Any] = []
        if normalized_channel:
            query += "AND lower(channel) = ? "
            params.append(normalized_channel)
        query += "ORDER BY timestamp ASC"

        with get_main_db() as db:
            rows = db.execute(query, tuple(params)).fetchall()

        cash = float(initial_cash)
        positions: dict[str, int] = {}
        for row in rows:
            ticker = str(row[0] or "")
            action = str(row[1] or "").upper()
            price = float(row[2] or 0.0)
            filled_price = float(row[3] or 0.0)
            quantity = int(row[4] or 0)
            filled_quantity = int(row[5] or 0)
            amount = float(row[6] or 0.0)
            commission = float(row[7] or 0.0)

            exec_qty = filled_quantity if filled_quantity > 0 else quantity
            exec_price = filled_price if filled_price > 0 else price
            exec_amount = amount if amount > 0 else exec_price * exec_qty
            if exec_qty <= 0:
                continue

            if action == "BUY":
                positions[ticker] = positions.get(ticker, 0) + exec_qty
                cash -= exec_amount + commission
            elif action == "SELL":
                positions[ticker] = positions.get(ticker, 0) - exec_qty
                cash += exec_amount - commission

        cleaned_positions = {k: v for k, v in positions.items() if v != 0}
        return {"cash": cash, "positions": cleaned_positions}

    @staticmethod
    def _normalize_status(status: Any) -> str:
        if hasattr(status, "value"):
            return str(status.value).lower()
        return str(status or "").lower()

    @staticmethod
    def _merge_status(old_status: str, new_status: str) -> str:
        if old_status in TERMINAL_STATUSES and old_status != "partial":
            return old_status
        if new_status:
            return new_status
        return old_status or "pending"

    @staticmethod
    def _is_same_trade(existing: dict[str, Any], trade: TradeRecord) -> bool:
        existing_meta = existing.get("metadata", {})
        trade_meta = trade.metadata or {}
        return (
            existing.get("ticker") == trade.ticker
            and str(existing.get("action", "")).upper() == str(trade.action).upper()
            and TradingLedger._normalize_status(existing.get("status")) == TradingLedger._normalize_status(trade.status)
            and float(existing.get("price", 0.0)) == float(trade.price or 0.0)
            and float(existing.get("filled_price", 0.0)) == float(trade.filled_price or 0.0)
            and int(existing.get("quantity", 0)) == int(trade.quantity or 0)
            and int(existing.get("filled_quantity", 0)) == int(trade.filled_quantity or 0)
            and float(existing.get("amount", 0.0)) == float(trade.amount or 0.0)
            and float(existing.get("commission", 0.0)) == float(trade.commission or 0.0)
            and existing_meta == trade_meta
        )

    @staticmethod
    def _json_loads(raw: Any) -> Any:
        if raw in (None, ""):
            return {}
        try:
            return json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _json_default(value: Any) -> Any:
        if isinstance(value, (bytes, bytearray)):
            return value.decode("utf-8", errors="ignore")
        item = getattr(value, "item", None)
        if callable(item):
            try:
                return item()
            except Exception:  # noqa: BLE001
                return str(value)
        if hasattr(value, "isoformat"):
            try:
                return value.isoformat()
            except Exception:  # noqa: BLE001
                return str(value)
        if hasattr(value, "value"):
            return value.value
        return str(value)

    @staticmethod
    def _direct_order_row_to_dict(row: Any) -> dict[str, Any]:
        response_payload = TradingLedger._json_loads(row[17])
        payload_trace = response_payload.get("trace", {}) if isinstance(response_payload, dict) else {}
        return {
            "id": str(row[0] or ""),
            "created_at": float(row[1] or 0.0),
            "updated_at": float(row[2] or 0.0),
            "request_id": str(row[3] or ""),
            "idempotency_key": str(row[4] or ""),
            "client_order_id": str(row[5] or ""),
            "local_order_id": str(row[6] or ""),
            "broker_order_id": str(row[7] or ""),
            "channel": str(row[8] or ""),
            "ticker": str(row[9] or ""),
            "side": str(row[10] or ""),
            "quantity": int(row[11] or 0),
            "price": float(row[12] or 0.0),
            "order_type": str(row[13] or ""),
            "status": str(row[14] or ""),
            "error_code": str(row[15] or ""),
            "error_message": str(row[16] or ""),
            "trace_id": str(
                response_payload.get("trace_id", "")
                or payload_trace.get("trace_id", "")
                if isinstance(response_payload, dict)
                else ""
            ),
            "response_payload": response_payload if isinstance(response_payload, dict) else {},
        }
