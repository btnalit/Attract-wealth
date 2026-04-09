"""
交易日历（A股）基础实现。

默认规则：
- 周六周日为非交易日
- 可通过配置追加节假日/调休日
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo


class CNTradingCalendar:
    def __init__(self, config_path: str | None = None):
        self.tz = ZoneInfo("Asia/Shanghai")
        root = Path(__file__).resolve().parent.parent.parent
        self.config_path = Path(config_path) if config_path else root / "config" / "trading_calendar_cn.json"
        self.holidays: set[date] = set()
        self.extra_workdays: set[date] = set()
        self._load_config()
        self._load_env_overrides()

    def today(self) -> date:
        return datetime.now(self.tz).date()

    def is_trading_day(self, target: date | None = None) -> bool:
        d = target or self.today()
        if d in self.extra_workdays:
            return True
        if d.weekday() >= 5:
            return False
        if d in self.holidays:
            return False
        return True

    def next_trading_day(self, from_date: date | None = None) -> date:
        d = from_date or self.today()
        while True:
            d = date.fromordinal(d.toordinal() + 1)
            if self.is_trading_day(d):
                return d

    def _load_config(self):
        if not self.config_path.exists():
            return
        try:
            payload = json.loads(self.config_path.read_text(encoding="utf-8"))
            self.holidays |= {self._parse_date(v) for v in payload.get("holidays", []) if self._parse_date(v)}
            self.extra_workdays |= {
                self._parse_date(v) for v in payload.get("extra_workdays", []) if self._parse_date(v)
            }
        except Exception:
            # 配置损坏时降级到仅周末规则
            self.holidays = set()
            self.extra_workdays = set()

    def _load_env_overrides(self):
        holidays = os.getenv("TRADING_HOLIDAYS", "").strip()
        workdays = os.getenv("TRADING_EXTRA_WORKDAYS", "").strip()
        if holidays:
            self.holidays |= {self._parse_date(v) for v in holidays.split(",") if self._parse_date(v.strip())}
        if workdays:
            self.extra_workdays |= {self._parse_date(v) for v in workdays.split(",") if self._parse_date(v.strip())}

    @staticmethod
    def _parse_date(raw: str) -> date | None:
        text = str(raw).strip()
        if not text:
            return None
        try:
            return datetime.strptime(text, "%Y-%m-%d").date()
        except ValueError:
            return None
