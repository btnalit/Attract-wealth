from __future__ import annotations

import json
import sqlite3

from src.dao.monitor_dao import MonitorDAO


def _build_main_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE accounts (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT DEFAULT 'simulation',
            balance REAL DEFAULT 0,
            total_pnl REAL DEFAULT 0,
            created_at REAL,
            updated_at REAL
        );
        CREATE TABLE positions (
            id TEXT PRIMARY KEY,
            ticker TEXT NOT NULL UNIQUE,
            market TEXT DEFAULT 'CN',
            quantity INTEGER NOT NULL DEFAULT 0,
            available INTEGER NOT NULL DEFAULT 0,
            avg_cost REAL NOT NULL DEFAULT 0,
            current_price REAL DEFAULT 0,
            unrealized_pnl REAL DEFAULT 0,
            market_value REAL DEFAULT 0,
            updated_at REAL
        );
        CREATE TABLE direct_order_requests (
            id TEXT PRIMARY KEY,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            request_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            client_order_id TEXT,
            local_order_id TEXT,
            broker_order_id TEXT,
            channel TEXT NOT NULL,
            ticker TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            price REAL NOT NULL,
            order_type TEXT DEFAULT 'limit',
            status TEXT DEFAULT 'received',
            error_code TEXT,
            error_message TEXT,
            response_payload TEXT
        );
        CREATE TABLE decision_evidence (
            id TEXT PRIMARY KEY,
            timestamp REAL NOT NULL,
            phase TEXT DEFAULT 'analyze',
            session_id TEXT,
            ticker TEXT NOT NULL,
            channel TEXT DEFAULT 'simulation',
            decision TEXT DEFAULT 'HOLD',
            confidence REAL DEFAULT 0,
            action TEXT DEFAULT 'HOLD',
            percentage REAL DEFAULT 0,
            reason TEXT,
            risk_passed INTEGER DEFAULT 1,
            risk_reason TEXT,
            evidence_payload TEXT
        );
        """
    )
    return conn


def _build_ledger_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE ledger_entries (
            id TEXT PRIMARY KEY,
            timestamp REAL NOT NULL,
            level TEXT DEFAULT 'INFO',
            category TEXT,
            agent_id TEXT,
            action TEXT,
            detail TEXT,
            status TEXT,
            metadata TEXT
        );
        """
    )
    return conn


def test_monitor_dao_aggregates_main_and_ledger_payloads() -> None:
    main_conn = _build_main_db()
    ledger_conn = _build_ledger_db()

    with main_conn as db:
        db.execute(
            """
            INSERT INTO accounts (id, name, type, balance, total_pnl, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("acc-1", "sim-main", "simulation", 1200000.0, 22300.0, 1710000000.0, 1710000900.0),
        )
        db.execute(
            """
            INSERT INTO positions (id, ticker, market, quantity, available, avg_cost, current_price, unrealized_pnl, market_value, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("pos-1", "600000", "CN", 1000, 1000, 10.2, 10.8, 600.0, 10800.0, 1710000900.0),
        )
        db.execute(
            """
            INSERT INTO direct_order_requests
            (id, created_at, updated_at, request_id, idempotency_key, channel, ticker, side, quantity, price, order_type, status, response_payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "dor-1",
                1710000800.0,
                1710000950.0,
                "req-1",
                "idem-1",
                "simulation",
                "600000",
                "BUY",
                100,
                10.6,
                "limit",
                "filled",
                json.dumps({"trace": {"trace_id": "trace-1"}}, ensure_ascii=False),
            ),
        )
        db.execute(
            """
            INSERT INTO decision_evidence
            (id, timestamp, phase, session_id, ticker, channel, decision, confidence, action, percentage, reason, risk_passed, risk_reason, evidence_payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "ev-1",
                1710000960.0,
                "execute",
                "session-1",
                "600000",
                "simulation",
                "BUY",
                0.83,
                "BUY",
                0.2,
                "signal ok",
                1,
                "",
                "{}",
            ),
        )

    with ledger_conn as db:
        db.execute(
            """
            INSERT INTO ledger_entries (id, timestamp, level, category, action, detail, status, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "le-1",
                1710000970.0,
                "ERROR",
                "RISK",
                "DIRECT_ORDER_RISK_REJECTED",
                "risk rejected order 600000",
                "rejected",
                json.dumps({"ticker": "600000"}, ensure_ascii=False),
            ),
        )
        db.execute(
            """
            INSERT INTO ledger_entries (id, timestamp, level, category, action, detail, status, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "le-2",
                1710000980.0,
                "INFO",
                "SYSTEM",
                "HEARTBEAT",
                "heartbeat",
                "success",
                "{}",
            ),
        )

    dao = MonitorDAO(main_db_factory=lambda: main_conn, ledger_db_factory=lambda: ledger_conn)

    account = dao.get_latest_account_snapshot()
    assert account["name"] == "sim-main"
    assert account["balance"] == 1200000.0

    positions = dao.list_top_positions(limit=3)
    assert len(positions) == 1
    assert positions[0]["ticker"] == "600000"
    assert positions[0]["market_value"] == 10800.0

    recent_orders = dao.list_recent_direct_orders(limit=5)
    assert len(recent_orders) == 1
    assert recent_orders[0]["request_id"] == "req-1"
    assert recent_orders[0]["trace_id"] == "trace-1"
    assert recent_orders[0]["status"] == "FILLED"

    decisions = dao.list_recent_decision_actions(limit=5)
    assert len(decisions) == 1
    assert decisions[0]["action"] == "BUY"
    assert decisions[0]["risk_passed"] is True

    alerts = dao.list_recent_risk_alerts(limit=5)
    assert len(alerts) == 1
    assert alerts[0]["category"] == "RISK"
    assert alerts[0]["severity"] == "high"

