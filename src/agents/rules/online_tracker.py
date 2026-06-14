# -*- coding: utf-8 -*-
"""在线信号验证调度器 (P2-1)。

定时（或每次分析后）扫描 signal_log 中"信号日 + forward_days <= 今天"且
未验证的信号，用当前收盘价回填 hit/未命中，形成在线准确率闭环。

调用方式：
    from src.agents.rules.online_tracker import verify_due_signals
    summary = verify_due_signals(forward_days=5)

该模块软失败：取价失败/异常时跳过该信号，不抛错。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from src.dao.signal_log_dao import SignalLogDAO, get_signal_log_dao

logger = logging.getLogger(__name__)


def _fetch_close(ticker: str) -> float | None:
    """拉取 ticker 当前最新收盘价（多源兜底）。"""
    try:
        from src.dataflows.china_data import ChinaDataAssembler
        import re

        numeric = re.sub(r"[^\d]", "", ticker)
        assembler = ChinaDataAssembler()
        df = assembler._get_kline(numeric, limit=5)
        if isinstance(df, pd.DataFrame) and not df.empty:
            cols = {str(c).lower(): c for c in df.columns}
            close_col = cols.get("close")
            if close_col is not None:
                return float(df.iloc[-1][close_col])
    except Exception as exc:  # noqa: BLE001
        logger.debug("取 %s 收盘价失败: %s", ticker, exc)
    return None


def _direction_hits(direction: str, forward_return: float) -> bool | None:
    """信号方向是否与未来收益一致。"""
    direction = str(direction).upper()
    if direction == "BULL":
        return forward_return > 0
    if direction == "BEAR":
        return forward_return < 0
    if direction == "NEUTRAL":
        return abs(forward_return) < 1.0
    return None


def verify_due_signals(
    *,
    forward_days: int = 5,
    ticker: str | None = None,
    dao: SignalLogDAO | None = None,
    price_fetcher=None,
) -> dict[str, Any]:
    """扫描到期未验证的信号并回填命中结果。

    Args:
        forward_days: 默认验证跨度；signal_log 中的 forward_days 为空时用此值
        ticker: 仅验证指定 ticker（None = 全部）
        dao: 注入 DAO（测试用）
        price_fetcher: 取价函数 ticker->close（测试用，默认 _fetch_close）

    Returns:
        {"checked": int, "verified": int, "skipped": int, "errors": int}
    """
    dao = dao or get_signal_log_dao()
    fetch = price_fetcher or _fetch_close
    today = datetime.now().date()

    pending = dao.list_unverified(ticker=ticker, limit=1000)
    summary = {"checked": 0, "verified": 0, "skipped": 0, "errors": 0}

    for sig in pending:
        summary["checked"] += 1
        signal_date_str = str(sig.get("signal_date", ""))
        try:
            signal_date = datetime.strptime(signal_date_str[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            summary["skipped"] += 1
            continue

        # 未到验证日（信号日 + forward_days 还没到今天）
        due_date = signal_date + timedelta(days=forward_days)
        if due_date > today:
            summary["skipped"] += 1
            continue

        ticker_id = str(sig.get("ticker", ""))
        close_now = fetch(ticker_id)
        if close_now is None or close_now <= 0:
            summary["errors"] += 1
            continue

        # 用记录里的 close_at_signal 推算 forward_return（mark_verified 内部也会算）
        close_at_signal = float(sig.get("close_at_signal") or 0.0)
        if close_at_signal <= 0:
            summary["skipped"] += 1
            continue
        forward_return = (close_now - close_at_signal) / close_at_signal * 100
        hit = _direction_hits(str(sig.get("direction", "")), forward_return)
        if hit is None:
            summary["skipped"] += 1
            continue

        try:
            dao.mark_verified(
                signal_id=str(sig.get("id")),
                forward_days=forward_days,
                close_at_verify=float(close_now),
                hit=bool(hit),
            )
            summary["verified"] += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("验证信号 %s 失败: %s", sig.get("id"), exc)
            summary["errors"] += 1

    return summary


def get_online_hit_rates(
    *, dao: SignalLogDAO | None = None, min_samples: int = 5
) -> dict[str, dict[str, Any]]:
    """获取按规则聚合的在线命中率（供 weights 校准使用）。"""
    dao = dao or get_signal_log_dao()
    return dao.get_online_accuracy(group_by="rule", min_samples=min_samples)
