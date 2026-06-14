# -*- coding: utf-8 -*-
"""P2-1：信号持久化 DAO + 在线准确率跟踪 单元测试。"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from src.dao.signal_log_dao import SignalLogDAO, _make_id
from src.agents.rules.online_tracker import verify_due_signals, get_online_hit_rates


def _make_dao(tmp_path: Path) -> SignalLogDAO:
    """构造一个用临时 DB 的 DAO（测试隔离）。"""
    db_path = tmp_path / "test_signal.db"

    def _factory() -> sqlite3.Connection:
        conn = sqlite3.connect(str(db_path))
        return conn

    return SignalLogDAO(db_factory=_factory)


# ===== SignalLogDAO 写入/读取 =====
class TestSignalLogWriteRead:
    def test_log_and_read_back(self, tmp_path):
        dao = _make_dao(tmp_path)
        n = dao.log_signals(
            ticker="000001",
            signal_date="2026-06-01",
            signals=[
                {"rule": "MA_GOLDEN_CROSS", "direction": "BULL", "strength": 70, "category": "trend"},
                {"rule": "RSI_OVERBOUGHT", "direction": "BEAR", "strength": 65, "category": "trend"},
            ],
            close_at_signal=10.0,
            analyst_type="Technical_Agent",
        )
        assert n == 2

        recent = dao.get_recent_signals(limit=10)
        assert len(recent) == 2
        rules = {r["rule"] for r in recent}
        assert "MA_GOLDEN_CROSS" in rules

    def test_log_empty_signals(self, tmp_path):
        dao = _make_dao(tmp_path)
        n = dao.log_signals(
            ticker="000001", signal_date="2026-06-01", signals=[], close_at_signal=10.0
        )
        assert n == 0

    def test_log_idempotent_overwrite(self, tmp_path):
        """相同 (ticker,date,rule,direction) 的信号只保留最新。"""
        dao = _make_dao(tmp_path)
        sig = [{"rule": "MA_GOLDEN_CROSS", "direction": "BULL", "strength": 60, "category": "trend"}]
        dao.log_signals(ticker="000001", signal_date="2026-06-01", signals=sig, close_at_signal=10.0)
        dao.log_signals(ticker="000001", signal_date="2026-06-01", signals=sig, close_at_signal=11.0)
        recent = dao.get_recent_signals()
        assert len(recent) == 1  # 覆盖，不重复
        assert recent[0]["close_at_signal"] == 11.0

    def test_make_id_deterministic(self):
        id1 = _make_id("000001", "2026-06-01", "MA_GOLDEN_CROSS", "BULL")
        id2 = _make_id("000001", "2026-06-01", "MA_GOLDEN_CROSS", "BULL")
        id3 = _make_id("000001", "2026-06-01", "MA_GOLDEN_CROSS", "BEAR")
        assert id1 == id2
        assert id1 != id3  # 方向不同 → id 不同


# ===== 验证 + 在线准确率 =====
class TestVerificationAndAccuracy:
    def test_mark_verified_updates_hit(self, tmp_path):
        dao = _make_dao(tmp_path)
        dao.log_signals(
            ticker="000001", signal_date="2026-06-01",
            signals=[{"rule": "MA_GOLDEN_CROSS", "direction": "BULL", "strength": 70, "category": "trend"}],
            close_at_signal=10.0,
        )
        unverified = dao.list_unverified()
        assert len(unverified) == 1
        sid = unverified[0]["id"]

        # BULL 信号，收盘从 10→10.5（+5%）→ 命中
        dao.mark_verified(signal_id=sid, forward_days=5, close_at_verify=10.5, hit=True)

        # 验证后不再出现在未验证列表
        unverified2 = dao.list_unverified()
        assert len(unverified2) == 0

        # 准确率统计
        acc = dao.get_online_accuracy(group_by="rule", min_samples=1)
        assert "MA_GOLDEN_CROSS" in acc
        assert acc["MA_GOLDEN_CROSS"]["hit_rate"] == 1.0
        assert acc["MA_GOLDEN_CROSS"]["avg_return"] == 5.0  # (10.5-10)/10*100

    def test_accuracy_filters_low_samples(self, tmp_path):
        """min_samples 过滤样本不足的分组。"""
        dao = _make_dao(tmp_path)
        dao.log_signals(
            ticker="000001", signal_date="2026-06-01",
            signals=[{"rule": "RARE_RULE", "direction": "BULL", "strength": 70, "category": "trend"}],
            close_at_signal=10.0,
        )
        sid = dao.list_unverified()[0]["id"]
        dao.mark_verified(signal_id=sid, forward_days=5, close_at_verify=11.0, hit=True)

        # min_samples=2 时只有 1 条样本的 RARE_RULE 被过滤
        acc = dao.get_online_accuracy(group_by="rule", min_samples=2)
        assert "RARE_RULE" not in acc

    def test_accuracy_group_by_analyst(self, tmp_path):
        dao = _make_dao(tmp_path)
        for i, analyst in enumerate(["Technical_Agent", "Technical_Agent", "Sentiment_Agent"]):
            dao.log_signals(
                ticker=f"00000{i}", signal_date="2026-06-01",
                signals=[{"rule": f"RULE_{i}", "direction": "BULL", "strength": 70, "category": "trend"}],
                close_at_signal=10.0, analyst_type=analyst,
            )
        for sig in dao.list_unverified():
            dao.mark_verified(signal_id=sig["id"], forward_days=5, close_at_verify=11.0, hit=True)

        acc = dao.get_online_accuracy(group_by="analyst_type", min_samples=1)
        assert "Technical_Agent" in acc
        assert acc["Technical_Agent"]["total"] == 2


# ===== online_tracker.verify_due_signals =====
class TestVerifyDueSignals:
    def test_future_signal_skipped(self, tmp_path):
        """信号日 + forward_days > 今天 → 跳过（未到验证日）。"""
        dao = _make_dao(tmp_path)
        # 今天的信号，forward_days=5 → 还没到验证日
        dao.log_signals(
            ticker="000001", signal_date=time.strftime("%Y-%m-%d"),
            signals=[{"rule": "MA_GOLDEN_CROSS", "direction": "BULL", "strength": 70, "category": "trend"}],
            close_at_signal=10.0,
        )
        summary = verify_due_signals(forward_days=5, dao=dao, price_fetcher=lambda t: 11.0)
        assert summary["verified"] == 0
        assert summary["skipped"] >= 1

    def test_past_signal_verified(self, tmp_path):
        """信号日 + forward_days <= 今天 → 取价验证。"""
        dao = _make_dao(tmp_path)
        # 30 天前的信号，forward_days=5 → 已到期
        from datetime import date, timedelta
        old_date = (date.today() - timedelta(days=30)).isoformat()
        dao.log_signals(
            ticker="000001", signal_date=old_date,
            signals=[{"rule": "MA_GOLDEN_CROSS", "direction": "BULL", "strength": 70, "category": "trend"}],
            close_at_signal=10.0,
        )
        # BULL 信号，价格涨到 11 → 命中
        summary = verify_due_signals(forward_days=5, dao=dao, price_fetcher=lambda t: 11.0)
        assert summary["verified"] == 1
        acc = dao.get_online_accuracy(group_by="rule", min_samples=1)
        assert acc["MA_GOLDEN_CROSS"]["hit_rate"] == 1.0

    def test_price_fetch_failure_counted_as_error(self, tmp_path):
        dao = _make_dao(tmp_path)
        from datetime import date, timedelta
        old_date = (date.today() - timedelta(days=30)).isoformat()
        dao.log_signals(
            ticker="000001", signal_date=old_date,
            signals=[{"rule": "MA_GOLDEN_CROSS", "direction": "BULL", "strength": 70, "category": "trend"}],
            close_at_signal=10.0,
        )
        summary = verify_due_signals(forward_days=5, dao=dao, price_fetcher=lambda t: None)
        assert summary["verified"] == 0
        assert summary["errors"] == 1

    def test_bear_signal_hit_on_decline(self, tmp_path):
        """BEAR 信号 + 价格下跌 → 命中。"""
        dao = _make_dao(tmp_path)
        from datetime import date, timedelta
        old_date = (date.today() - timedelta(days=30)).isoformat()
        dao.log_signals(
            ticker="000001", signal_date=old_date,
            signals=[{"rule": "MA_DEATH_CROSS", "direction": "BEAR", "strength": 70, "category": "trend"}],
            close_at_signal=10.0,
        )
        # 价格跌到 9.5 (-5%) → BEAR 命中
        summary = verify_due_signals(forward_days=5, dao=dao, price_fetcher=lambda t: 9.5)
        assert summary["verified"] == 1
        acc = dao.get_online_accuracy(group_by="rule", min_samples=1)
        assert acc["MA_DEATH_CROSS"]["hit_rate"] == 1.0
