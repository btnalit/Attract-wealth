from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src.core.errors import TradingServiceError
from src.core.storage import STRATEGY_SCHEMA
from src.core.strategy_store import StrategyStore


def _db_factory(db_path: Path):
    def _open():
        conn = sqlite3.connect(str(db_path))
        conn.executescript(STRATEGY_SCHEMA)
        return conn

    return _open


def _make_store(db_name: str, monkeypatch: pytest.MonkeyPatch) -> StrategyStore:
    monkeypatch.setattr(StrategyStore, "_record_audit", staticmethod(lambda **kwargs: None))
    tmp_root = Path(__file__).resolve().parents[2] / "_pytest_tmp"
    tmp_root.mkdir(parents=True, exist_ok=True)
    db_path = tmp_root / db_name
    db_path.unlink(missing_ok=True)
    return StrategyStore(db_factory=_db_factory(db_path))


def test_create_strategy_version_increments_version(monkeypatch: pytest.MonkeyPatch):
    store = _make_store("strategies_test.db", monkeypatch)

    s1 = store.create_strategy_version(name="momentum", parameters={"lookback": 3}, status="draft")
    s2 = store.create_strategy_version(name="momentum", parameters={"lookback": 5}, status="candidate")

    assert s1["version"] == 1
    assert s2["version"] == 2
    items = store.list_strategy_versions(name="momentum")
    assert len(items) == 2


def test_gate_and_promote_flow(monkeypatch: pytest.MonkeyPatch):
    store = _make_store("strategies_gate.db", monkeypatch)

    base = store.create_strategy_version(
        name="mean_revert",
        parameters={"lookback": 3},
        metrics={"trade_count": 40, "win_rate": 0.6, "max_drawdown": 0.1, "net_pnl": 2000, "sharpe": 1.2},
        status="active",
    )
    candidate = store.create_strategy_version(
        name="mean_revert",
        parent_id=base["id"],
        parameters={"lookback": 5},
        metrics={"trade_count": 10, "win_rate": 0.3, "max_drawdown": 0.4, "net_pnl": -10, "sharpe": 0.1},
        status="candidate",
    )

    gate_fail = store.evaluate_version_gate(candidate["id"], persist=False)
    assert gate_fail["passed"] is False
    with pytest.raises(TradingServiceError) as exc_info:
        store.promote_strategy_version(candidate["id"], operator="unit_test", force=False, gate_result=gate_fail)
    assert exc_info.value.code == "STRATEGY_VERSION_GATE_FAILED"

    store.update_strategy_metrics(
        candidate["id"],
        {"trade_count": 60, "win_rate": 0.62, "max_drawdown": 0.12, "net_pnl": 4500, "sharpe": 1.35},
        merge=True,
    )
    gate_ok = store.evaluate_version_gate(candidate["id"], persist=True)
    assert gate_ok["passed"] is True
    promoted = store.promote_strategy_version(candidate["id"], operator="unit_test", gate_result=gate_ok)
    assert promoted["strategy"]["status"] == "active"

    base_after = store.get_strategy(base["id"])
    assert base_after["status"] == "candidate"


def test_state_machine_transition_constraints(monkeypatch: pytest.MonkeyPatch):
    store = _make_store("strategies_state_machine.db", monkeypatch)
    strategy = store.create_strategy_version(
        name="state_flow",
        status="draft",
        metrics={"trade_count": 10, "win_rate": 0.2, "max_drawdown": 0.4, "net_pnl": -100, "sharpe": 0.1},
    )

    with pytest.raises(TradingServiceError) as exc_info:
        store.transition_strategy_status(strategy["id"], target_status="active", operator="unit")
    assert exc_info.value.code == "STRATEGY_STATUS_TRANSITION_INVALID"

    with pytest.raises(TradingServiceError) as gate_exc:
        store.transition_strategy_status(strategy["id"], target_status="candidate", operator="unit")
    assert gate_exc.value.code == "STRATEGY_CANDIDATE_GATE_FAILED"

    store.update_strategy_metrics(
        strategy["id"],
        {"trade_count": 40, "win_rate": 0.62, "max_drawdown": 0.12, "net_pnl": 2300, "sharpe": 1.1},
        merge=True,
    )
    to_candidate = store.transition_strategy_status(strategy["id"], target_status="candidate", operator="unit")
    assert to_candidate["strategy"]["status"] == "candidate"

    to_active = store.transition_strategy_status(strategy["id"], target_status="active", operator="unit")
    assert to_active["strategy"]["status"] == "active"


def test_gate_rules_resolve_by_market_and_template(monkeypatch: pytest.MonkeyPatch):
    store = _make_store("strategies_gate_market_template.db", monkeypatch)
    monkeypatch.setenv(
        "STRATEGY_GATE_RULES_JSON",
        json.dumps(
            {
                "markets": {"CN": {"min_win_rate": 0.6}},
                "templates": {"momentum": {"min_sharpe": 1.0}},
                "market_template": {"CN": {"momentum": {"min_trades": 30}}},
            }
        ),
    )

    strategy = store.create_strategy_version(
        name="alpha_momo",
        market="CN",
        strategy_template="momentum",
        metrics={
            "trade_count": 28,
            "win_rate": 0.58,
            "max_drawdown": 0.1,
            "net_pnl": 1000,
            "sharpe": 1.1,
        },
        status="candidate",
    )

    failed = store.evaluate_version_gate(strategy["id"], persist=False)
    assert failed["passed"] is False
    assert failed["gate_context"]["market"] == "CN"
    assert failed["gate_context"]["strategy_template"] == "momentum"
    assert failed["gate"]["min_trades"] == 30
    assert failed["gate"]["min_win_rate"] == 0.6

    passed = store.evaluate_version_gate(
        strategy["id"],
        persist=False,
        overrides={"min_trades": 20, "min_win_rate": 0.55},
    )
    assert passed["passed"] is True
    assert passed["gate_context"]["manual_overrides"]["min_trades"] == 20
    assert passed["gate_context"]["manual_overrides"]["min_win_rate"] == 0.55


def test_archive_backtest_report_roundtrip(monkeypatch: pytest.MonkeyPatch):
    store = _make_store("strategies_backtest_archive.db", monkeypatch)

    strategy = store.create_strategy_version(
        name="carry",
        market="CN",
        strategy_template="swing",
        metrics={"win_rate": 0.5},
        status="candidate",
    )
    report = {
        "strategy": {"id": strategy["id"], "name": strategy["name"], "version": strategy["version"]},
        "metrics": {"trade_count": 22, "win_rate": 0.63, "max_drawdown": 0.11, "net_pnl": 3200, "sharpe": 1.4},
        "summary": {"bars": 120, "final_equity": 1003200},
    }

    archived = store.archive_backtest_report(
        strategy_id=strategy["id"],
        report=report,
        market="CN",
        strategy_template="swing",
        run_tag="nightly_001",
        source="api",
        bars_hash="bars_hash_x",
        params_hash="params_hash_y",
        trace_context={"bars": [{"close": 10.0}], "parameters": {"lookback": 3}},
    )
    assert archived["strategy_id"] == strategy["id"]
    assert archived["market"] == "CN"
    assert archived["strategy_template"] == "swing"
    assert archived["run_tag"] == "nightly_001"

    listed = store.list_backtest_reports(strategy_id=strategy["id"], limit=10)
    assert len(listed) == 1
    assert listed[0]["id"] == archived["id"]
    assert listed[0]["bars_hash"] == "bars_hash_x"

    detail = store.get_backtest_report(archived["id"])
    assert detail["trace_index"]["report_id"] == archived["id"]
    assert detail["report_payload"]["backtest"]["summary"]["bars"] == 120
