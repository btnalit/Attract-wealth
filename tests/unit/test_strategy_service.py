from __future__ import annotations

from src.services.strategy_service import StrategyService


class _FakeStore:
    def __init__(self):
        self.calls: list[str] = []

    def create_strategy_version(self, **kwargs):
        self.calls.append("create")
        return {"ok": True, "name": kwargs.get("name", "")}

    def list_strategy_versions(self, **kwargs):
        self.calls.append("list")
        return [{"id": "s1", "name": kwargs.get("name", "demo")}]

    def get_strategy(self, strategy_id: str):
        self.calls.append("get")
        return {"id": strategy_id}

    def update_strategy_metrics(self, strategy_id: str, metrics: dict, *, merge: bool = True):
        self.calls.append("update_metrics")
        return {"id": strategy_id, "metrics": metrics, "merge": merge}

    def evaluate_version_gate(self, strategy_id: str, **kwargs):
        self.calls.append("gate")
        return {"strategy_id": strategy_id, "passed": True, "overrides": kwargs.get("overrides", {})}

    def promote_strategy_version(self, strategy_id: str, **kwargs):
        self.calls.append("promote")
        return {"strategy_id": strategy_id, "status": "active", "kwargs": kwargs}

    def transition_strategy_status(self, strategy_id: str, **kwargs):
        self.calls.append("transition")
        return {"strategy_id": strategy_id, "to_status": kwargs.get("target_status", "")}

    def archive_backtest_report(self, **kwargs):
        self.calls.append("archive")
        return {"id": "r1", "strategy_id": kwargs.get("strategy_id", "")}

    def list_backtest_reports(self, **kwargs):
        self.calls.append("list_reports")
        return [{"id": "r1", "strategy_id": kwargs.get("strategy_id", "")}]

    def get_backtest_report(self, report_id: str):
        self.calls.append("get_report")
        return {"id": report_id}


class _FakeRunner:
    def __init__(self):
        self.calls = 0

    def run(self, **kwargs):
        self.calls += 1
        return {"summary": {"bars": len(kwargs.get("bars", []))}}


def test_strategy_service_wraps_store_and_runner_calls():
    store = _FakeStore()
    runner = _FakeRunner()
    service = StrategyService(strategy_store=store, backtest_runner=runner)

    assert service.create_strategy_version(name="demo")["ok"] is True
    assert service.list_strategy_versions(name="demo")[0]["id"] == "s1"
    assert service.get_strategy("s1")["id"] == "s1"
    assert service.update_strategy_metrics("s1", {"win_rate": 0.6})["id"] == "s1"
    assert service.evaluate_version_gate("s1")["passed"] is True
    assert service.transition_strategy_status("s1", target_status="candidate")["to_status"] == "candidate"
    assert service.promote_strategy_version("s1")["status"] == "active"
    assert service.archive_backtest_report(strategy_id="s1")["id"] == "r1"
    assert service.list_backtest_reports(strategy_id="s1")[0]["id"] == "r1"
    assert service.get_backtest_report("r1")["id"] == "r1"

    report = service.run_backtest(strategy_id="s1", bars=[{"timestamp": "2026-01-01", "close": 10.0}])
    assert report["summary"]["bars"] == 1
    assert runner.calls == 1
