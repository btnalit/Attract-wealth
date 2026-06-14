"""G7-2/G7-3 回归测试：MemoryManager 数据安全与 maintenance。

重点验证：
- demote WARM->COLD 时若 COLD 写失败，WARM 记录必须保留（不丢数据）
- promote COLD->WARM 时若 WARM 写失败，COLD 必须保留
- auto_maintenance 不重复处理同一 id
- auto_maintenance 过期+容量合并后不超量 demote
"""
from __future__ import annotations

import sqlite3
import time
from unittest.mock import patch

import pytest

from src.evolution.memory_manager import MemoryManager


@pytest.fixture()
def manager(tmp_path):
    return MemoryManager(data_dir=str(tmp_path))


def _insert_warm_with_ts(mgr: MemoryManager, entry_id: str, created_ts: float):
    """直接向 warm_memory 表插入一条带指定时间戳的记录（绕过 write 的 now()）。"""
    with sqlite3.connect(str(mgr.warm_db_path)) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO warm_memory "
            "(id, content, tags, created_at, access_count, importance_score, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (entry_id, entry_id, "[]", created_ts, 0, 0.5, "{}"),
        )
        conn.commit()


class TestDemoteDataSafety:
    def test_demote_warm_to_cold_failure_keeps_warm(self, manager):
        """COLD 写失败时，WARM 记录不能丢。"""
        mid = manager.write("warm", "important memory", tags=["t"])
        assert mid is not None

        # 让 _write_cold 返回 False（模拟磁盘写失败）
        with patch.object(manager, "_write_cold", return_value=False):
            manager.demote(mid)

        # WARM 必须仍然存在
        results = manager.search("important", memory_type="warm", limit=10)
        assert any(m.id == mid for m in results), "WARM 记录在 COLD 写失败后不应被删除"

    def test_demote_hot_to_warm_failure_restores_hot(self, manager):
        """HOT->WARM 时 WARM 写失败，条目应回到 HOT。"""
        mid = manager.write("hot", "hot memory", tags=["t"])
        assert mid in manager.hot_memory

        with patch.object(manager, "_write_warm", return_value=False):
            manager.demote(mid)

        # 应该仍在 HOT
        assert mid in manager.hot_memory, "HOT 条目在 WARM 写失败后应恢复"

    def test_promote_cold_to_warm_failure_keeps_cold(self, manager):
        """COLD->WARM 时 WARM 写失败，COLD 文件不能丢。"""
        mid = manager.write("cold", "cold memory", tags=["t"])
        # 确认 cold 文件存在
        cold_entry = manager._get_from_cold(mid)
        assert cold_entry is not None

        with patch.object(manager, "_write_warm", return_value=False):
            manager.promote(mid)

        # COLD 必须仍在
        assert manager._get_from_cold(mid) is not None, "COLD 在 WARM 写失败后不应被删除"


class TestAutoMaintenanceNoDuplicates:
    def test_expired_and_overflow_merged_no_double_demote(self, manager):
        """过期 demote 与容量 demote 不应让同一 id 被处理两次。"""
        old_ts = time.time() - (manager.WARM_EXPIRY_DAYS * 24 * 3600 + 100)
        for i in range(5):
            _insert_warm_with_ts(manager, f"expired_{i}", old_ts)

        for i in range(3):
            manager.write("warm", f"fresh_{i}")

        manager.WARM_MAX_CAPACITY = 2

        demote_calls: list[str] = []
        original_demote = manager.demote

        def _spy_demote(memory_id):
            demote_calls.append(memory_id)
            return original_demote(memory_id)

        with patch.object(manager, "demote", side_effect=_spy_demote):
            manager.auto_maintenance()

        # 同一 id 不应被 demote 两次
        assert len(demote_calls) == len(set(demote_calls)), "auto_maintenance 不应重复处理同一 id"

    def test_maintenance_reduces_overflow(self, manager):
        """维护后 WARM 数量不应超过容量上限。"""
        old_ts = time.time() - (manager.WARM_EXPIRY_DAYS * 24 * 3600 + 100)
        for i in range(10):
            _insert_warm_with_ts(manager, f"item_{i}", old_ts)

        manager.WARM_MAX_CAPACITY = 3
        manager.auto_maintenance()

        with sqlite3.connect(str(manager.warm_db_path)) as conn:
            count = conn.execute("SELECT COUNT(*) FROM warm_memory").fetchone()[0]
        # 全部过期，应全部被 demote，WARM 应接近 0
        assert count <= manager.WARM_MAX_CAPACITY
