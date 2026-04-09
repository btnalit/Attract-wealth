"""
Storage layer for LaiCai.

SQLite is used in WAL mode for local reliability and simple deployment.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DATA_DIR = Path(os.getenv("DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "data")))

MAIN_DB = DATA_DIR / "laicai.db"
LEDGER_DB = DATA_DIR / "trading_ledger.db"
STRATEGY_DB = DATA_DIR / "strategies.db"

MAIN_SCHEMA = """
CREATE TABLE IF NOT EXISTS trading_records (
    id              TEXT PRIMARY KEY,
    timestamp       REAL NOT NULL,
    ticker          TEXT NOT NULL,
    market          TEXT DEFAULT 'CN',
    action          TEXT NOT NULL,
    price           REAL,
    filled_price    REAL,
    quantity        INTEGER,
    filled_quantity INTEGER,
    amount          REAL,
    pnl             REAL DEFAULT 0,
    commission      REAL DEFAULT 0,
    confidence      REAL,
    agent_id        TEXT,
    session_id      TEXT,
    channel         TEXT DEFAULT 'simulation',
    status          TEXT DEFAULT 'pending',
    metadata        TEXT
);

CREATE TABLE IF NOT EXISTS analysis_reports (
    id          TEXT PRIMARY KEY,
    timestamp   REAL NOT NULL,
    ticker      TEXT NOT NULL,
    report_type TEXT,
    agent_id    TEXT,
    content     TEXT,
    decision    TEXT,
    confidence  REAL,
    metadata    TEXT
);

CREATE TABLE IF NOT EXISTS positions (
    id             TEXT PRIMARY KEY,
    ticker         TEXT NOT NULL UNIQUE,
    market         TEXT DEFAULT 'CN',
    quantity       INTEGER NOT NULL DEFAULT 0,
    available      INTEGER NOT NULL DEFAULT 0,
    avg_cost       REAL NOT NULL DEFAULT 0,
    current_price  REAL DEFAULT 0,
    unrealized_pnl REAL DEFAULT 0,
    updated_at     REAL
);

CREATE TABLE IF NOT EXISTS accounts (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    type       TEXT DEFAULT 'simulation',
    balance    REAL DEFAULT 1000000,
    total_pnl  REAL DEFAULT 0,
    created_at REAL,
    updated_at REAL
);

CREATE TABLE IF NOT EXISTS llm_costs (
    id            TEXT PRIMARY KEY,
    timestamp     REAL NOT NULL,
    provider      TEXT,
    model         TEXT,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    cost_usd      REAL,
    agent_id      TEXT,
    session_id    TEXT
);

CREATE TABLE IF NOT EXISTS decision_evidence (
    id              TEXT PRIMARY KEY,
    timestamp       REAL NOT NULL,
    phase           TEXT DEFAULT 'analyze',
    session_id      TEXT,
    ticker          TEXT NOT NULL,
    channel         TEXT DEFAULT 'simulation',
    decision        TEXT DEFAULT 'HOLD',
    confidence      REAL DEFAULT 0,
    action          TEXT DEFAULT 'HOLD',
    percentage      REAL DEFAULT 0,
    reason          TEXT,
    risk_passed     INTEGER DEFAULT 1,
    risk_reason     TEXT,
    evidence_payload TEXT
);

CREATE TABLE IF NOT EXISTS reconciliation_reports (
    id           TEXT PRIMARY KEY,
    timestamp    REAL NOT NULL,
    channel      TEXT,
    status       TEXT,
    issues_count INTEGER DEFAULT 0,
    snapshot     TEXT
);

CREATE TABLE IF NOT EXISTS direct_order_requests (
    id               TEXT PRIMARY KEY,
    created_at       REAL NOT NULL,
    updated_at       REAL NOT NULL,
    request_id       TEXT NOT NULL,
    idempotency_key  TEXT NOT NULL UNIQUE,
    client_order_id  TEXT,
    local_order_id   TEXT,
    broker_order_id  TEXT,
    channel          TEXT NOT NULL,
    ticker           TEXT NOT NULL,
    side             TEXT NOT NULL,
    quantity         INTEGER NOT NULL,
    price            REAL NOT NULL,
    order_type       TEXT DEFAULT 'limit',
    status           TEXT DEFAULT 'received',
    error_code       TEXT,
    error_message    TEXT,
    response_payload TEXT
);

CREATE TABLE IF NOT EXISTS watchlists (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    tickers    TEXT NOT NULL,
    source     TEXT DEFAULT 'system',
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS system_settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS trading_memory (
    id               TEXT PRIMARY KEY,
    tier             TEXT NOT NULL,
    category         TEXT,
    trigger_scenario TEXT,
    content          TEXT,
    source_ids       TEXT,
    confidence       REAL DEFAULT 0.5,
    hit_count        INTEGER DEFAULT 0,
    created_at       REAL,
    promoted_at      REAL
);

CREATE INDEX IF NOT EXISTS idx_records_ticker ON trading_records(ticker);
CREATE INDEX IF NOT EXISTS idx_records_timestamp ON trading_records(timestamp);
CREATE INDEX IF NOT EXISTS idx_reports_ticker ON analysis_reports(ticker);
CREATE INDEX IF NOT EXISTS idx_llm_costs_timestamp ON llm_costs(timestamp);
CREATE INDEX IF NOT EXISTS idx_llm_costs_session ON llm_costs(session_id);
CREATE INDEX IF NOT EXISTS idx_llm_costs_agent ON llm_costs(agent_id);
CREATE INDEX IF NOT EXISTS idx_recon_timestamp ON reconciliation_reports(timestamp);
CREATE INDEX IF NOT EXISTS idx_recon_status ON reconciliation_reports(status);
CREATE INDEX IF NOT EXISTS idx_evidence_timestamp ON decision_evidence(timestamp);
CREATE INDEX IF NOT EXISTS idx_evidence_session ON decision_evidence(session_id);
CREATE INDEX IF NOT EXISTS idx_evidence_ticker ON decision_evidence(ticker);
CREATE INDEX IF NOT EXISTS idx_watchlists_updated ON watchlists(updated_at);
CREATE INDEX IF NOT EXISTS idx_memory_tier ON trading_memory(tier);
CREATE INDEX IF NOT EXISTS idx_direct_order_request_id ON direct_order_requests(request_id);
CREATE INDEX IF NOT EXISTS idx_direct_order_local_id ON direct_order_requests(local_order_id);
CREATE INDEX IF NOT EXISTS idx_direct_order_client_id ON direct_order_requests(client_order_id);
CREATE INDEX IF NOT EXISTS idx_direct_order_updated_at ON direct_order_requests(updated_at);
"""

LEDGER_SCHEMA = """
CREATE TABLE IF NOT EXISTS ledger_entries (
    id        TEXT PRIMARY KEY,
    timestamp REAL NOT NULL,
    level     TEXT DEFAULT 'INFO',
    category  TEXT,
    agent_id  TEXT,
    action    TEXT,
    detail    TEXT,
    status    TEXT,
    metadata  TEXT
);

CREATE INDEX IF NOT EXISTS idx_ledger_timestamp ON ledger_entries(timestamp);
CREATE INDEX IF NOT EXISTS idx_ledger_category ON ledger_entries(category);
"""

STRATEGY_SCHEMA = """
CREATE TABLE IF NOT EXISTS strategies (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    version    INTEGER DEFAULT 1,
    parent_id  TEXT,
    origin     TEXT,
    content    TEXT,
    parameters TEXT,
    metrics    TEXT,
    status     TEXT DEFAULT 'active',
    created_at REAL,
    updated_at REAL
);

CREATE INDEX IF NOT EXISTS idx_strategies_name ON strategies(name);

CREATE TABLE IF NOT EXISTS strategy_backtest_reports (
    id                TEXT PRIMARY KEY,
    strategy_id       TEXT NOT NULL,
    strategy_name     TEXT NOT NULL,
    strategy_version  INTEGER NOT NULL DEFAULT 1,
    market            TEXT DEFAULT 'CN',
    strategy_template TEXT DEFAULT 'default',
    run_tag           TEXT DEFAULT '',
    source            TEXT DEFAULT 'api',
    bars_hash         TEXT DEFAULT '',
    params_hash       TEXT DEFAULT '',
    metrics           TEXT,
    summary           TEXT,
    trace_index       TEXT,
    report_payload    TEXT,
    created_at        REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_backtest_reports_strategy_id ON strategy_backtest_reports(strategy_id);
CREATE INDEX IF NOT EXISTS idx_backtest_reports_name_ver ON strategy_backtest_reports(strategy_name, strategy_version);
CREATE INDEX IF NOT EXISTS idx_backtest_reports_market_tpl ON strategy_backtest_reports(market, strategy_template);
CREATE INDEX IF NOT EXISTS idx_backtest_reports_run_tag ON strategy_backtest_reports(run_tag);
CREATE INDEX IF NOT EXISTS idx_backtest_reports_created_at ON strategy_backtest_reports(created_at);
"""


# 全局连接与初始化状态缓存
_DB_STATE = {
    "initialized": False,
    "connections": {}
}


def _init_db(db_path: Path, schema: str) -> sqlite3.Connection:
    """初始化数据库并返回连接。如果已初始化，则仅返回连接。"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA cache_size=-64000")
    
    # 架构审查优化：仅在未初始化时执行 Schema
    # 我们使用一个轻量级的检查，看是否已经有表存在
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    if not cursor.fetchone():
        conn.executescript(schema)
        conn.commit()
        
    return conn


def reset_connections():
    """测试用：重置全局连接池，防止 teardown 后复用失效连接。"""
    global _DB_STATE
    _DB_STATE["connections"] = {}
    _DB_STATE["initialized"] = False


def get_db_connection(db_path: Path, schema: str) -> sqlite3.Connection:
    """带缓存的数据库连接获取函数。"""
    path_str = str(db_path)
    if path_str not in _DB_STATE["connections"]:
        _DB_STATE["connections"][path_str] = _init_db(db_path, schema)
    return _DB_STATE["connections"][path_str]


def init_all_databases():
    """系统启动时调用的全量初始化函数。"""
    if _DB_STATE["initialized"]:
        return
    print(f"Initializing databases in: {DATA_DIR}")
    get_db_connection(MAIN_DB, MAIN_SCHEMA)
    get_db_connection(LEDGER_DB, LEDGER_SCHEMA)
    get_db_connection(STRATEGY_DB, STRATEGY_SCHEMA)
    _DB_STATE["initialized"] = True
    print("Database initialization completed")


def get_main_db() -> sqlite3.Connection:
    return get_db_connection(MAIN_DB, MAIN_SCHEMA)


def get_ledger_db() -> sqlite3.Connection:
    return get_db_connection(LEDGER_DB, LEDGER_SCHEMA)


def get_strategy_db() -> sqlite3.Connection:
    return get_db_connection(STRATEGY_DB, STRATEGY_SCHEMA)


if __name__ == "__main__":
    init_all_databases()
