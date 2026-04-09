"""
L1 (memory) + L2 (SQLite) cache with observability metrics.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import date, datetime
from typing import Any, Optional

from src.core.storage import DATA_DIR

CACHE_DB = DATA_DIR / "cache.db"


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return item()
        except Exception:  # noqa: BLE001
            return str(value)
    return str(value)


class CacheManager:
    """Two-level cache manager (Memory + SQLite)."""

    def __init__(self, memory_ttl: int = 60):
        self._memory_cache: dict[str, dict[str, Any]] = {}
        self.memory_ttl = memory_ttl
        self._lock = threading.RLock()
        self._metrics: dict[str, int] = {
            "requests": 0,
            "memory_hits": 0,
            "sqlite_hits": 0,
            "misses": 0,
            "writes": 0,
            "memory_expired": 0,
            "sqlite_expired": 0,
            "sqlite_cleanups": 0,
            "sqlite_cleanup_removed": 0,
        }
        self._init_sqlite()

    def _init_sqlite(self):
        CACHE_DB.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(CACHE_DB), check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS kv_cache (
                key TEXT PRIMARY KEY,
                value TEXT,
                expire_at REAL
            )
            """
        )
        self.conn.commit()

    def _clean_sqlite(self):
        now = time.time()
        cur = self.conn.execute("DELETE FROM kv_cache WHERE expire_at > 0 AND expire_at < ?", (now,))
        removed = int(cur.rowcount or 0)
        self.conn.commit()
        self._metrics["sqlite_cleanups"] += 1
        self._metrics["sqlite_cleanup_removed"] += max(removed, 0)

    def get(self, key: str) -> Optional[Any]:
        now = time.time()
        with self._lock:
            self._metrics["requests"] += 1

            entry = self._memory_cache.get(key)
            if entry is not None:
                if entry["expire_at"] == 0 or entry["expire_at"] > now:
                    self._metrics["memory_hits"] += 1
                    return entry["value"]
                self._metrics["memory_expired"] += 1
                self._memory_cache.pop(key, None)

            cur = self.conn.execute("SELECT value, expire_at FROM kv_cache WHERE key = ?", (key,))
            row = cur.fetchone()
            if row is None:
                self._metrics["misses"] += 1
                return None

            value_str, expire_at = row
            if expire_at == 0 or expire_at > now:
                try:
                    val = json.loads(value_str)
                except Exception:  # noqa: BLE001
                    self.conn.execute("DELETE FROM kv_cache WHERE key = ?", (key,))
                    self.conn.commit()
                    self._metrics["misses"] += 1
                    return None

                self._memory_cache[key] = {"value": val, "expire_at": expire_at}
                self._metrics["sqlite_hits"] += 1
                return val

            self.conn.execute("DELETE FROM kv_cache WHERE key = ?", (key,))
            self.conn.commit()
            self._metrics["sqlite_expired"] += 1
            self._metrics["misses"] += 1
            return None

    def set(self, key: str, value: Any, ttl: int = 300) -> None:
        """Write cache item. ttl=0 means never expire."""
        now = time.time()
        expire_at = now + ttl if ttl > 0 else 0
        value_str = json.dumps(value, ensure_ascii=False, default=_json_default)

        with self._lock:
            self._memory_cache[key] = {"value": value, "expire_at": expire_at}
            self.conn.execute(
                """
                INSERT INTO kv_cache (key, value, expire_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, expire_at=excluded.expire_at
                """,
                (key, value_str, expire_at),
            )
            self.conn.commit()
            self._metrics["writes"] += 1

            # Low-cost probabilistic cleanup
            if int(time.time()) % 20 == 0:
                self._clean_sqlite()

    def delete(self, key: str) -> None:
        with self._lock:
            self._memory_cache.pop(key, None)
            self.conn.execute("DELETE FROM kv_cache WHERE key = ?", (key,))
            self.conn.commit()

    def reset_metrics(self) -> None:
        with self._lock:
            for metric_key in self._metrics:
                self._metrics[metric_key] = 0

    def get_metrics(self) -> dict[str, Any]:
        with self._lock:
            requests = self._metrics["requests"]
            memory_hits = self._metrics["memory_hits"]
            sqlite_hits = self._metrics["sqlite_hits"]
            total_hits = memory_hits + sqlite_hits
            misses = self._metrics["misses"]
            hit_rate = total_hits / requests if requests else 0.0
            backsource_rate = misses / requests if requests else 0.0
            memory_hit_ratio = memory_hits / total_hits if total_hits else 0.0
            sqlite_hit_ratio = sqlite_hits / total_hits if total_hits else 0.0

            return {
                "requests": requests,
                "hits": total_hits,
                "misses": misses,
                "memory_hits": memory_hits,
                "sqlite_hits": sqlite_hits,
                "writes": self._metrics["writes"],
                "hit_rate": round(hit_rate, 4),
                "backsource_rate": round(backsource_rate, 4),
                "memory_hit_ratio": round(memory_hit_ratio, 4),
                "sqlite_hit_ratio": round(sqlite_hit_ratio, 4),
                "memory_expired": self._metrics["memory_expired"],
                "sqlite_expired": self._metrics["sqlite_expired"],
                "sqlite_cleanups": self._metrics["sqlite_cleanups"],
                "sqlite_cleanup_removed": self._metrics["sqlite_cleanup_removed"],
                "memory_entries": len(self._memory_cache),
            }


cache_manager = CacheManager()
