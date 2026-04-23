from __future__ import annotations

import sqlite3

from src.core.storage import STRATEGY_SCHEMA
from src.core.strategy_store import StrategyStore


def test_strategy_store_chain_create_gate_archive_list_get(monkeypatch):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.executescript(STRATEGY_SCHEMA)

    monkeypatch.setattr(StrategyStore, "_record_audit", staticmethod(lambda **kwargs: None))
    store = StrategyStore(db_factory=lambda: conn)

    created = store.create_strategy_version(
        name="chain_demo",
        content='{"logic":"ma_cross"}',
        parameters={"lookback": 5, "market": "CN", "strategy_template": "momentum"},
        metrics={"trade_count": 25, "win_rate": 0.61, "max_drawdown": 0.12, "net_pnl": 1200, "sharpe": 1.1},
        status="candidate",
    )
    assert created["id"]

    gate = store.evaluate_version_gate(created["id"], persist=True, market="CN", strategy_template="momentum")
    assert "passed" in gate
    assert gate["strategy_id"] == created["id"]

    archive = store.archive_backtest_report(
        strategy_id=created["id"],
        report={
            "metrics": {"trade_count": 30, "win_rate": 0.63, "max_drawdown": 0.1, "net_pnl": 1500, "sharpe": 1.2},
            "summary": {"bars": 3},
        },
        market="CN",
        strategy_template="momentum",
        run_tag="unit_chain",
        source="pytest",
        bars_hash="bars_hash_demo",
        params_hash="params_hash_demo",
    )
    assert archive["id"]

    rows = store.list_backtest_reports(strategy_id=created["id"], limit=10)
    assert len(rows) == 1
    assert rows[0]["id"] == archive["id"]

    detail = store.get_backtest_report(archive["id"])
    assert detail["id"] == archive["id"]
    assert detail["strategy_id"] == created["id"]
    assert detail["metrics"]["net_pnl"] == 1500
