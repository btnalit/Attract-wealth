# -*- coding: utf-8 -*-
"""
来财 (Attract-wealth) — 直接下单保护器
剥离自 TradingService，负责在 API 直接下单时的安全过滤。
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Set

logger = logging.getLogger(__name__)


def _is_env_true(key: str, default: bool = False) -> bool:
    v = os.getenv(key, str(default)).lower()
    return v in ("true", "1", "yes", "on")


def _parse_csv_set(v: str) -> Set[str]:
    if not v:
        return set()
    return {x.strip() for x in v.split(",") if x.strip()}


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


def _to_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (ValueError, TypeError):
        return default


class DirectOrderGuard:
    def __init__(self, calendar: Any):
        self.calendar = calendar
        self.enabled = _is_env_true("DIRECT_ORDER_GUARD_ENABLED", default=True)
        self.require_manual_confirm = _is_env_true("DIRECT_ORDER_REQUIRE_MANUAL_CONFIRM", default=False)
        self.confirm_token = str(os.getenv("DIRECT_ORDER_CONFIRM_TOKEN", "")).strip()
        self.whitelist_enabled = _is_env_true("DIRECT_ORDER_WHITELIST_ENABLED", default=False)
        self.ticker_whitelist = _parse_csv_set(os.getenv("DIRECT_ORDER_TICKER_WHITELIST", ""))
        self.max_orders_per_minute = max(1, _to_int(os.getenv("DIRECT_ORDER_MAX_ORDERS_PER_MINUTE", "20"), 20))
        self.max_notional_per_order = max(0.0, _to_float(os.getenv("DIRECT_ORDER_MAX_NOTIONAL_PER_ORDER", "0")))
        self.max_notional_per_day = max(0.0, _to_float(os.getenv("DIRECT_ORDER_MAX_NOTIONAL_PER_DAY", "0")))
        self.enforce_trading_window = _is_env_true("DIRECT_ORDER_ENFORCE_TRADING_WINDOW", default=False)
        self.allow_non_trading_day = _is_env_true("DIRECT_ORDER_ALLOW_NON_TRADING_DAY", default=False)
        self.sessions = self._parse_sessions(os.getenv("DIRECT_ORDER_TRADING_SESSIONS", "09:30-11:30,13:00-15:00"))
        
        self.recent_requests: list[float] = []
        self.daily_notional = 0.0
        self.daily_marker = self.calendar.today().isoformat()

    def _parse_sessions(self, raw: str) -> list[tuple[str, str]]:
        sessions = []
        for chunk in str(raw or "").split(","):
            text = chunk.strip()
            if not text or "-" not in text:
                continue
            start, end = text.split("-", 1)
            start = start.strip()
            end = end.strip()
            if len(start) >= 4 and len(end) >= 4:
                sessions.append((start, end))
        return sessions if sessions else [("09:30", "11:30"), ("13:00", "15:00")]

    def check(self, ticker: str, side: str, price: float, quantity: int, manual_confirm: bool = False, confirm_token: str = "") -> tuple[bool, str]:
        """执行安全检查。返回 (是否通过, 错误原因)。"""
        if not self.enabled:
            return True, ""

        now = time.time()
        today = self.calendar.today().isoformat()

        # 1. 检查交易日 + 时间窗口
        if self.enforce_trading_window:
            is_trading_day = self.calendar.is_trading_day(self.calendar.today())
            
            if not is_trading_day and not self.allow_non_trading_day:
                return False, "非交易日禁止直接下单"
            
            # Check trading window (sessions)
            import datetime
            now_dt = datetime.datetime.now()
            now_hm = now_dt.strftime("%H:%M")
            in_window = False
            for start, end in self.sessions:
                if start <= now_hm <= end:
                    in_window = True
                    break
            if not in_window:
                return False, "当前时间不在交易窗口内"

        # 2. 检查频率 (1分钟内)
        self.recent_requests = [t for t in self.recent_requests if now - t < 60]
        if len(self.recent_requests) >= self.max_orders_per_minute:
            return False, f"下单频率超过限制: {self.max_orders_per_minute}/min"

        # 3. 检查白名单
        if self.whitelist_enabled and ticker not in self.ticker_whitelist:
            return False, f"股票 {ticker} 不在允许交易的白名单中"

        # 4. 检查单笔限额
        notional = price * quantity
        if self.max_notional_per_order > 0 and notional > self.max_notional_per_order:
            return False, f"单笔委托金额 ¥{notional:,.2f} 超过限制 ¥{self.max_notional_per_order:,.2f}"

        # 5. 检查单日总额
        if self.daily_marker != today:
            self.daily_marker = today
            self.daily_notional = 0.0
        
        if self.max_notional_per_day > 0 and (self.daily_notional + notional) > self.max_notional_per_day:
            return False, f"今日累计委托金额已达上限 ¥{self.max_notional_per_day:,.2f}"

        # 6. 检查人工确认
        if self.require_manual_confirm and not manual_confirm:
            return False, "该操作需要人工确认标记 (manual_confirm=true)"
        
        if self.require_manual_confirm and self.confirm_token and confirm_token != self.confirm_token:
            return False, "人工确认 Token 错误"

        # 记录通过
        self.recent_requests.append(now)
        self.daily_notional += notional
        return True, ""

    def get_status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "whitelist_enabled": self.whitelist_enabled,
            "daily_notional": self.daily_notional,
            "max_notional_per_day": self.max_notional_per_day,
            "requests_last_minute": len(self.recent_requests),
        }
