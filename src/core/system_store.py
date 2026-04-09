"""
Persistent store for system-level runtime data.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Iterable

from src.core.storage import get_main_db


class SystemStore:
    DEFAULT_WATCHLIST_NAME = "default"
    AUTOPILOT_TEMPLATE_KEY = "autopilot_template"

    @staticmethod
    def normalize_tickers(tickers: Iterable[str]) -> list[str]:
        seen: set[str] = set()
        normalized: list[str] = []
        for raw in tickers:
            text = str(raw or "").strip().upper()
            if not text:
                continue
            parts = [item.strip() for item in text.split(",") if item.strip()]
            for ticker in parts:
                if ticker in seen:
                    continue
                seen.add(ticker)
                normalized.append(ticker)
        return normalized

    def load_watchlist(self, name: str = DEFAULT_WATCHLIST_NAME) -> list[str]:
        with get_main_db() as db:
            row = db.execute("SELECT tickers FROM watchlists WHERE name = ?", (name,)).fetchone()
        if not row:
            return []
        try:
            payload = json.loads(row[0])
        except (TypeError, json.JSONDecodeError):
            return []
        if not isinstance(payload, list):
            return []
        return self.normalize_tickers(payload)

    def watchlist_exists(self, name: str = DEFAULT_WATCHLIST_NAME) -> bool:
        with get_main_db() as db:
            row = db.execute("SELECT 1 FROM watchlists WHERE name = ? LIMIT 1", (name,)).fetchone()
        return bool(row)

    def save_watchlist(
        self,
        tickers: Iterable[str],
        name: str = DEFAULT_WATCHLIST_NAME,
        source: str = "api",
    ) -> list[str]:
        normalized = self.normalize_tickers(tickers)
        now = time.time()
        with get_main_db() as db:
            db.execute(
                """
                INSERT INTO watchlists (id, name, tickers, source, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    tickers = excluded.tickers,
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                (
                    str(uuid.uuid4()),
                    name,
                    json.dumps(normalized, ensure_ascii=False),
                    source,
                    now,
                ),
            )
        return normalized

    def load_or_bootstrap_watchlist(self, fallback: Iterable[str]) -> list[str]:
        saved = self.load_watchlist()
        if saved:
            return saved
        return self.save_watchlist(fallback, source="bootstrap")

    def set_setting(self, key: str, value: Any):
        now = time.time()
        with get_main_db() as db:
            db.execute(
                """
                INSERT INTO system_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, json.dumps(value, ensure_ascii=False), now),
            )

    def get_setting(self, key: str, default: Any = None) -> Any:
        with get_main_db() as db:
            row = db.execute("SELECT value FROM system_settings WHERE key = ?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row[0])
        except (TypeError, json.JSONDecodeError):
            return default

    def set_autopilot_template(self, template_name: str):
        self.set_setting(self.AUTOPILOT_TEMPLATE_KEY, str(template_name or "").strip())

    def get_autopilot_template(self, default: str = "") -> str:
        value = self.get_setting(self.AUTOPILOT_TEMPLATE_KEY, default)
        return str(value or default).strip()
