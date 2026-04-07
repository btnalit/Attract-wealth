"""
来财 数据库存储层 — SQLite WAL 模式

高性能交易数据存储，继承 OpsSentry 的 WAL 模式设计。
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

# 数据库文件路径
DATA_DIR = Path(os.getenv("DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "data")))

MAIN_DB = DATA_DIR / "laicai.db"
LEDGER_DB = DATA_DIR / "trading_ledger.db"
STRATEGY_DB = DATA_DIR / "strategies.db"

# === Schema 定义 ===

MAIN_SCHEMA = """
-- 交易记录表
CREATE TABLE IF NOT EXISTS trading_records (
    id          TEXT PRIMARY KEY,
    timestamp   REAL NOT NULL,
    ticker      TEXT NOT NULL,
    market      TEXT DEFAULT 'CN',
    action      TEXT NOT NULL,
    price       REAL,
    filled_price REAL,
    quantity    INTEGER,
    filled_quantity INTEGER,
    amount      REAL,
    pnl         REAL DEFAULT 0,
    commission  REAL DEFAULT 0,
    confidence  REAL,
    agent_id    TEXT,
    session_id  TEXT,
    channel     TEXT DEFAULT 'simulation',
    status      TEXT DEFAULT 'pending',
    metadata    TEXT
);

-- 分析报告表
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

-- 持仓表
CREATE TABLE IF NOT EXISTS positions (
    id          TEXT PRIMARY KEY,
    ticker      TEXT NOT NULL UNIQUE,
    market      TEXT DEFAULT 'CN',
    quantity    INTEGER NOT NULL DEFAULT 0,
    available   INTEGER NOT NULL DEFAULT 0,
    avg_cost    REAL NOT NULL DEFAULT 0,
    current_price REAL DEFAULT 0,
    unrealized_pnl REAL DEFAULT 0,
    updated_at  REAL
);

-- 账户表
CREATE TABLE IF NOT EXISTS accounts (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    type        TEXT DEFAULT 'simulation',
    balance     REAL DEFAULT 1000000,
    total_pnl   REAL DEFAULT 0,
    created_at  REAL,
    updated_at  REAL
);

-- LLM 调用成本记录
CREATE TABLE IF NOT EXISTS llm_costs (
    id          TEXT PRIMARY KEY,
    timestamp   REAL NOT NULL,
    provider    TEXT,
    model       TEXT,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    cost_usd    REAL,
    agent_id    TEXT,
    session_id  TEXT
);

-- 交易记忆表
CREATE TABLE IF NOT EXISTS trading_memory (
    id          TEXT PRIMARY KEY,
    tier        TEXT NOT NULL,
    category    TEXT,
    trigger_scenario TEXT,
    content     TEXT,
    source_ids  TEXT,
    confidence  REAL DEFAULT 0.5,
    hit_count   INTEGER DEFAULT 0,
    created_at  REAL,
    promoted_at REAL
);

CREATE INDEX IF NOT EXISTS idx_records_ticker ON trading_records(ticker);
CREATE INDEX IF NOT EXISTS idx_records_timestamp ON trading_records(timestamp);
CREATE INDEX IF NOT EXISTS idx_reports_ticker ON analysis_reports(ticker);
CREATE INDEX IF NOT EXISTS idx_memory_tier ON trading_memory(tier);
"""

LEDGER_SCHEMA = """
-- 审计日志表 (不可删改)
CREATE TABLE IF NOT EXISTS ledger_entries (
    id          TEXT PRIMARY KEY,
    timestamp   REAL NOT NULL,
    level       TEXT DEFAULT 'INFO',
    category    TEXT,
    agent_id    TEXT,
    action      TEXT,
    detail      TEXT,
    status      TEXT,
    metadata    TEXT
);

CREATE INDEX IF NOT EXISTS idx_ledger_timestamp ON ledger_entries(timestamp);
CREATE INDEX IF NOT EXISTS idx_ledger_category ON ledger_entries(category);
"""

STRATEGY_SCHEMA = """
-- 策略版本表
CREATE TABLE IF NOT EXISTS strategies (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    version     INTEGER DEFAULT 1,
    parent_id   TEXT,
    origin      TEXT,
    content     TEXT,
    parameters  TEXT,
    metrics     TEXT,
    status      TEXT DEFAULT 'active',
    created_at  REAL,
    updated_at  REAL
);

CREATE INDEX IF NOT EXISTS idx_strategies_name ON strategies(name);
"""


def _init_db(db_path: Path, schema: str) -> sqlite3.Connection:
    """初始化数据库连接 (WAL 模式)"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
    conn.executescript(schema)
    conn.commit()
    return conn


def init_all_databases():
    """初始化所有数据库"""
    print(f"📦 初始化数据库: {DATA_DIR}")
    _init_db(MAIN_DB, MAIN_SCHEMA)
    _init_db(LEDGER_DB, LEDGER_SCHEMA)
    _init_db(STRATEGY_DB, STRATEGY_SCHEMA)
    print("✅ 数据库初始化完成")


def get_main_db() -> sqlite3.Connection:
    return _init_db(MAIN_DB, MAIN_SCHEMA)


def get_ledger_db() -> sqlite3.Connection:
    return _init_db(LEDGER_DB, LEDGER_SCHEMA)


def get_strategy_db() -> sqlite3.Connection:
    return _init_db(STRATEGY_DB, STRATEGY_SCHEMA)


if __name__ == "__main__":
    init_all_databases()
