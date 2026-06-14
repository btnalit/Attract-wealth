"""复查（R1/R2）回归测试：验证第二轮修复的正确性。

R1: G7-5 actual_pnl 不再因 build_portfolio_snapshot 无 realized_pnl 字段而恒为 0。
R2: G7-2 _write_warm 抛非 sqlite3.Error 异常时仍返回 False（不破坏 promote/demote 安全）。
R2: promote/demote 写失败时 entry.memory_type 恢复原值（无对象状态污染）。
"""
from __future__ import annotations

import os
import sqlite3
from unittest.mock import patch

import pytest

from src.evolution.memory_manager import MemoryManager
from src.evolution.reflector import ObservationData, TradingReflector


@pytest.fixture()
def manager(tmp_path):
    return MemoryManager(data_dir=str(tmp_path))


class TestWriteWarmBroadException:
    """R2：_write_warm 必须捕获所有异常返回 False，不能抛出。"""

    def test_write_warm_returns_false_on_non_sqlite_error(self, manager, monkeypatch):
        """模拟磁盘满（OSError）等非 sqlite3.Error 异常，_write_warm 应返回 False。"""
        import src.evolution.memory_manager as mod

        def _raising_connect(_path):
            raise OSError("disk full simulated")

        monkeypatch.setattr(mod.sqlite3, "connect", _raising_connect)
        from src.evolution.memory_manager import MemoryEntry
        entry = MemoryEntry(content="x", memory_type="warm")
        # 不能抛出，必须返回 False
        result = manager._write_warm(entry)
        assert result is False

    def test_demote_warm_to_cold_safe_when_warm_write_raises(self, manager, monkeypatch):
        """HOT->WARM 时若 _write_warm 抛 OSError，条目应回到 HOT 而非丢失。"""
        mid = manager.write("hot", "hot item", tags=["t"])
        assert mid in manager.hot_memory

        import src.evolution.memory_manager as mod

        original_connect = mod.sqlite3.connect
        call_count = {"n": 0}

        def _flaky_connect(path):
            call_count["n"] += 1
            # 第一次连接（_get_from_warm 不触发，因为这是 HOT 路径）
            # 直接让所有 connect 抛 OSError
            raise OSError("flaky disk")

        monkeypatch.setattr(mod.sqlite3, "connect", _flaky_connect)
        manager.demote(mid)
        # 条目应仍在 HOT
        assert mid in manager.hot_memory, "HOT 条目在 WARM 写抛异常后应恢复"


class TestMemoryTypeNoPollution:
    """R2：promote/demote 写失败时 entry.memory_type 应回到原值。"""

    def test_demote_warm_to_cold_failure_restores_memory_type(self, manager):
        mid = manager.write("warm", "warm item", tags=["t"])
        entry_before = manager._get_from_warm(mid)
        assert entry_before is not None
        assert entry_before.memory_type == "warm"

        with patch.object(manager, "_write_cold", return_value=False):
            manager.demote(mid)

        # entry 从 _get_from_warm 重新读取，确认 memory_type 仍为 warm（未被污染成 cold）
        entry_after = manager._get_from_warm(mid)
        assert entry_after is not None, "WARM 记录应保留"
        assert entry_after.memory_type == "warm", "写失败后 memory_type 不应被污染"

    def test_promote_cold_to_warm_failure_restores_memory_type(self, manager):
        mid = manager.write("cold", "cold item", tags=["t"])
        entry_before = manager._get_from_cold(mid)
        assert entry_before is not None
        assert entry_before.memory_type == "cold"

        with patch.object(manager, "_write_warm", return_value=False):
            manager.promote(mid)

        entry_after = manager._get_from_cold(mid)
        assert entry_after is not None, "COLD 记录应保留"
        assert entry_after.memory_type == "cold", "写失败后 memory_type 不应被污染"


class TestReflectorActualPnlFromCash:
    """R1：actual_pnl 应从组合快照的 cash 字段推导，不再恒为 0。"""

    @staticmethod
    def _make_reflector():
        """构造最小 TradingReflector 实例（只调 _orient，无需真实 ledger/store）。"""
        r = TradingReflector.__new__(TradingReflector)
        r.llm_client = None
        return r

    def test_actual_pnl_uses_cash_delta(self):
        """portfolio_snapshot.cash 相对 initial_cash 的差值即为已实现盈亏。"""
        data = ObservationData(
            date="2026-06-15",
            trades=[],
            ledger_entries=[],
            agent_logs=[],
            portfolio_snapshot={"cash": 1_050_000.0, "positions": {}},
        )
        report = self._make_reflector()._orient(data)
        assert report.actual_pnl == pytest.approx(50_000.0)
        assert report.metrics["actual_pnl"] == pytest.approx(50_000.0)

    def test_actual_pnl_negative_when_loss(self):
        data = ObservationData(
            date="2026-06-15",
            trades=[],
            ledger_entries=[],
            agent_logs=[],
            portfolio_snapshot={"cash": 950_000.0, "positions": {}},
        )
        report = self._make_reflector()._orient(data)
        assert report.actual_pnl == pytest.approx(-50_000.0)

    def test_actual_pnl_falls_back_to_trade_pnl_when_snapshot_missing_cash(self):
        """快照无 cash 字段（数据缺失）但 trade 有 pnl 时，回退用 trade 求和。"""
        data = ObservationData(
            date="2026-06-15",
            trades=[
                {"metadata": {"pnl": 100}},
                {"metadata": {"pnl": -30}},
            ],
            ledger_entries=[],
            agent_logs=[],
            portfolio_snapshot={"positions": {}},  # 无 cash 字段
        )
        report = self._make_reflector()._orient(data)
        # 100 + (-30) = 70
        assert report.actual_pnl == pytest.approx(70.0)

    def test_actual_pnl_uses_snapshot_cash_even_when_zero(self):
        """cash==initial 是合法的 0 盈亏真值，不应被 trade pnl 覆盖。"""
        data = ObservationData(
            date="2026-06-15",
            trades=[{"metadata": {"pnl": 999}}],  # trade 声称盈利，但快照才权威
            ledger_entries=[],
            agent_logs=[],
            portfolio_snapshot={"cash": 1_000_000.0, "positions": {}},  # pnl=0
        )
        report = self._make_reflector()._orient(data)
        assert report.actual_pnl == pytest.approx(0.0)

    def test_actual_pnl_zero_when_no_data(self):
        """无快照无 trade pnl 时，actual_pnl 为 0（数据不足）。"""
        data = ObservationData(
            date="2026-06-15",
            trades=[],
            ledger_entries=[],
            agent_logs=[],
            portfolio_snapshot={},
        )
        report = self._make_reflector()._orient(data)
        assert report.actual_pnl == pytest.approx(0.0)

