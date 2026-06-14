# -*- coding: utf-8 -*-
"""信号持久化 DAO (P2-1)。

把每次分析周期产出的规则信号落盘到 SQLite，并在未来 N 日后用实际收盘价
回填"命中/未命中"，形成在线准确率统计 —— 这是离线回测的在线版闭环。

表结构（自管理，DAO 首次访问时自动建表，不依赖启动初始化）：

    signal_log(
        id            TEXT PRIMARY KEY,   -- ticker|date|rule|direction 哈希
        ticker        TEXT NOT NULL,
        signal_date   TEXT NOT NULL,      -- 信号当日 YYYY-MM-DD
        rule          TEXT NOT NULL,
        direction     TEXT NOT NULL,      -- BULL/BEAR/NEUTRAL
        strength      REAL,
        category      TEXT,
        close_at_signal REAL,             -- 信号当日收盘价
        analyst_type  TEXT,               -- 发出该信号的 analyst
        created_at    REAL NOT NULL,
        -- 验证字段（未来 N 日后回填）
        verified_at   REAL,
        forward_days  INTEGER,
        close_at_verify REAL,             -- 验证日收盘价
        forward_return_pct REAL,
        hit           INTEGER             -- 1/0/NULL（未验证）
    )

设计原则：
- 自管理表：首次连接时 CREATE TABLE IF NOT EXISTS，兼容已存在的 laicai.db
- 幂等：同一 ticker+date+rule+direction 重复写入只保留最新一条
- 软依赖：DAO 失败不影响主分析链路（调用方 try/except）
"""
from __future__ import annotations

import hashlib
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable

from src.core.storage import DATA_DIR, get_main_db

logger = logging.getLogger(__name__)

SIGNAL_LOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS signal_log (
    id              TEXT PRIMARY KEY,
    ticker          TEXT NOT NULL,
    signal_date     TEXT NOT NULL,
    rule            TEXT NOT NULL,
    direction       TEXT NOT NULL,
    strength        REAL,
    category        TEXT,
    close_at_signal REAL,
    analyst_type    TEXT,
    created_at      REAL NOT NULL,
    verified_at     REAL,
    forward_days    INTEGER,
    close_at_verify REAL,
    forward_return_pct REAL,
    hit             INTEGER
);
CREATE INDEX IF NOT EXISTS idx_signal_log_ticker ON signal_log(ticker);
CREATE INDEX IF NOT EXISTS idx_signal_log_date ON signal_log(signal_date);
CREATE INDEX IF NOT EXISTS idx_signal_log_rule ON signal_log(rule);
CREATE INDEX IF NOT EXISTS idx_signal_log_unverified ON signal_log(hit) WHERE hit IS NULL;
CREATE INDEX IF NOT EXISTS idx_signal_log_verified ON signal_log(verified_at);
"""

_DB_LOCK = threading.Lock()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """首次访问时确保 signal_log 表存在（自管理，幂等）。"""
    try:
        conn.executescript(SIGNAL_LOG_SCHEMA)
        conn.commit()
    except sqlite3.OperationalError as exc:
        logger.warning("signal_log 建表失败（可能已存在）: %s", exc)


def _make_id(ticker: str, signal_date: str, rule: str, direction: str) -> str:
    raw = f"{ticker}|{signal_date}|{rule}|{direction}".encode("utf-8")
    return hashlib.md5(raw).hexdigest()[:16]


class SignalLogDAO:
    """信号持久化 + 在线准确率跟踪 DAO。"""

    def __init__(
        self,
        db_factory: Callable[[], sqlite3.Connection] | None = None,
    ) -> None:
        self._db_factory = db_factory or get_main_db
        self._initialized = False

    def _db(self) -> sqlite3.Connection:
        conn = self._db_factory()
        if not self._initialized:
            _ensure_schema(conn)
            self._initialized = True
        return conn

    # -------------------------
    # 写入：记录信号
    # -------------------------
    def log_signals(
        self,
        *,
        ticker: str,
        signal_date: str,
        signals: Iterable[dict[str, Any]],
        close_at_signal: float | None = None,
        analyst_type: str = "",
    ) -> int:
        """批量写入一个分析周期产出的信号。

        幂等：相同 (ticker, signal_date, rule, direction) 的信号会被覆盖更新。

        Returns:
            实际写入/更新的行数
        """
        rows = []
        now = time.time()
        for sig in signals:
            if not isinstance(sig, dict):
                continue
            rule = str(sig.get("rule", "")).strip()
            direction = str(sig.get("direction", "NEUTRAL")).upper()
            if not rule:
                continue
            rows.append((
                _make_id(ticker, signal_date, rule, direction),
                ticker,
                signal_date,
                rule,
                direction,
                float(sig.get("strength", 0.0) or 0.0),
                str(sig.get("category", "") or ""),
                close_at_signal,
                analyst_type,
                now,
            ))
        if not rows:
            return 0

        with _DB_LOCK:
            conn = self._db()
            conn.executemany(
                """
                INSERT OR REPLACE INTO signal_log
                    (id, ticker, signal_date, rule, direction, strength,
                     category, close_at_signal, analyst_type, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()
        return len(rows)

    # -------------------------
    # 读取：待验证信号
    # -------------------------
    def list_unverified(
        self, *, ticker: str | None = None, limit: int = 500
    ) -> list[dict[str, Any]]:
        """列出尚未验证的信号（hit IS NULL）。"""
        sql = (
            "SELECT id, ticker, signal_date, rule, direction, strength, "
            "close_at_signal, analyst_type, created_at "
            "FROM signal_log WHERE hit IS NULL"
        )
        params: list[Any] = []
        if ticker:
            sql += " AND ticker = ?"
            params.append(ticker)
        sql += " ORDER BY created_at ASC LIMIT ?"
        params.append(max(1, int(limit)))

        with _DB_LOCK:
            conn = self._db()
            cur = conn.execute(sql, params)
            rows = cur.fetchall()

        cols = ["id", "ticker", "signal_date", "rule", "direction",
                "strength", "close_at_signal", "analyst_type", "created_at"]
        return [dict(zip(cols, r)) for r in rows]

    # -------------------------
    # 写入：验证命中
    # -------------------------
    def mark_verified(
        self,
        *,
        signal_id: str,
        forward_days: int,
        close_at_verify: float,
        hit: bool,
    ) -> None:
        """回填一条信号的验证结果。

        Args:
            signal_id: signal_log.id
            forward_days: 验证跨度天数
            close_at_verify: 验证日收盘价
            hit: 信号方向是否与未来收益一致
        """
        # 计算 forward_return（需要从已存的 close_at_signal 推算）
        with _DB_LOCK:
            conn = self._db()
            cur = conn.execute(
                "SELECT close_at_signal FROM signal_log WHERE id = ?",
                (signal_id,),
            )
            row = cur.fetchone()
            if not row:
                return
            close_at_signal = float(row[0]) if row[0] is not None else 0.0
            forward_return = (
                (close_at_verify - close_at_signal) / close_at_signal * 100
                if close_at_signal else 0.0
            )
            conn.execute(
                """
                UPDATE signal_log SET
                    verified_at = ?,
                    forward_days = ?,
                    close_at_verify = ?,
                    forward_return_pct = ?,
                    hit = ?
                WHERE id = ?
                """,
                (time.time(), int(forward_days), float(close_at_verify),
                 round(forward_return, 4), 1 if hit else 0, signal_id),
            )
            conn.commit()

    # -------------------------
    # 读取：在线准确率聚合
    # -------------------------
    def get_online_accuracy(
        self,
        *,
        group_by: str = "rule",
        min_samples: int = 5,
    ) -> dict[str, dict[str, Any]]:
        """聚合已验证信号的在线命中率。

        Args:
            group_by: "rule" 或 "analyst_type"
            min_samples: 样本数低于此值的分组被剔除（统计不可靠）

        Returns:
            {group_key: {"total": int, "hits": int, "hit_rate": float,
                          "avg_return": float}}
        """
        if group_by not in ("rule", "analyst_type"):
            group_by = "rule"
        # 注意：SQLite 不允许在 HAVING/ORDER BY 中引用 SELECT 别名 hit_rate，
        # 故在 Python 层排序（样本量小，无性能问题）。
        sql = f"""
            SELECT {group_by} AS gk,
                   COUNT(*) AS total,
                   SUM(CASE WHEN hit = 1 THEN 1 ELSE 0 END) AS hits,
                   AVG(forward_return_pct) AS avg_ret
            FROM signal_log
            WHERE hit IS NOT NULL
            GROUP BY gk
            HAVING total >= ?
        """
        with _DB_LOCK:
            conn = self._db()
            cur = conn.execute(sql, (int(min_samples),))
            rows = cur.fetchall()

        # Python 层按命中率降序排序
        def _hit_rate(row: tuple) -> float:
            total = int(row[1])
            return (int(row[2] or 0) / total) if total else 0.0
        rows = sorted(rows, key=_hit_rate, reverse=True)

        result: dict[str, dict[str, Any]] = {}
        for gk, total, hits, avg_ret in rows:
            total_i = int(total)
            hits_i = int(hits or 0)
            result[str(gk or "")] = {
                "total": total_i,
                "hits": hits_i,
                "hit_rate": round(hits_i / total_i, 4) if total_i else 0.0,
                "avg_return": round(float(avg_ret or 0.0), 4),
            }
        return result

    def get_recent_signals(
        self, *, ticker: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """最近信号列表（供前端展示 + 审计）。"""
        sql = (
            "SELECT id, ticker, signal_date, rule, direction, strength, "
            "category, close_at_signal, analyst_type, created_at, "
            "verified_at, forward_days, close_at_verify, "
            "forward_return_pct, hit FROM signal_log"
        )
        params: list[Any] = []
        if ticker:
            sql += " WHERE ticker = ?"
            params.append(ticker)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, int(limit)))

        with _DB_LOCK:
            conn = self._db()
            cur = conn.execute(sql, params)
            rows = cur.fetchall()

        cols = ["id", "ticker", "signal_date", "rule", "direction", "strength",
                "category", "close_at_signal", "analyst_type", "created_at",
                "verified_at", "forward_days", "close_at_verify",
                "forward_return_pct", "hit"]
        return [dict(zip(cols, r)) for r in rows]


# 模块级单例（懒加载）
_dao_instance: SignalLogDAO | None = None


def get_signal_log_dao() -> SignalLogDAO:
    global _dao_instance
    if _dao_instance is None:
        _dao_instance = SignalLogDAO()
    return _dao_instance
