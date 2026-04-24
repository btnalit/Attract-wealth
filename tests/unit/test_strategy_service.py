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
        return [
            {
                "id": "s1",
                "name": kwargs.get("name", "demo"),
                "version": 1,
                "origin": "BUILT_IN",
                "status": "candidate",
                "created_at": 1.0,
                "metrics": {
                    "trade_count": 28,
                    "win_rate": 0.61,
                    "max_drawdown": 0.12,
                    "net_pnl": 1520.0,
                    "sharpe": 0.93,
                },
            }
        ]

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


def test_strategy_service_list_strategy_history_returns_structured_ooda():
    service = StrategyService(strategy_store=_FakeStore(), backtest_runner=_FakeRunner())

    events = service.list_strategy_history(limit=20)
    assert len(events) == 1

    event = events[0]
    assert event["id"] == "s1"
    assert event["type"] == "BASE"
    assert event["strategy_name"] == "demo"
    assert "status: candidate" in event["message"]
    assert isinstance(event["ooda"], dict)
    assert "win rate" in event["ooda"]["orient"]
    assert event["ooda"]["trades"] == 28
    assert isinstance(event["ooda"]["deviations"], int)


def test_strategy_service_knowledge_methods():
    class _FakeKnowledgeCore:
        def __init__(self):
            self.deleted_ids: list[str] = []

        def search_patterns(self, query: str, top_k: int):
            return [{"id": "p1", "query": query, "top_k": top_k}]

        def search_lessons(self, query: str, top_k: int):
            return [{"id": "l1", "query": query, "top_k": top_k}]

        def search_rules(self, query: str, top_k: int):
            return [{"id": "r1", "query": query, "top_k": top_k}]

        def search_all(self, query: str, top_k: int):
            return {"patterns": [], "lessons": [], "rules": [{"id": "r-all", "query": query, "top_k": top_k}]}

        def add_pattern(self, name: str, description: str, context: dict):
            return f"p::{name}::{description}::{context.get('source', '')}"

        def add_lesson(self, title: str, content: str, tags: list[str]):
            return f"l::{title}::{content}::{len(tags)}"

        def add_expert_rule(self, rule_text: str, priority: int = 0):
            return f"r::{rule_text}::{priority}"

        def delete_entry(self, entry_id: str):
            self.deleted_ids.append(entry_id)
            return entry_id == "exists-id"

    fake_core = _FakeKnowledgeCore()
    service = StrategyService(strategy_store=_FakeStore(), backtest_runner=_FakeRunner())
    service._create_knowledge_core = lambda: fake_core  # type: ignore[method-assign]

    assert service.search_knowledge(knowledge_type="pattern", query_text="breakout", top_k=5)[0]["id"] == "p1"
    assert service.search_knowledge(knowledge_type="lesson", query_text="risk", top_k=3)[0]["id"] == "l1"
    assert service.search_knowledge(knowledge_type="rule", query_text="stop loss", top_k=2)[0]["id"] == "r1"
    assert "rules" in service.search_knowledge(knowledge_type="all", query_text="all", top_k=4)

    pattern_payload = service.ingest_knowledge(
        knowledge_type="pattern",
        title="Breakout",
        content="Volume confirms breakout",
        tags=["pattern"],
        context={"source": "test"},
    )
    assert pattern_payload["id"].startswith("p::")
    assert pattern_payload["entry_type"] == "pattern"

    lesson_payload = service.ingest_knowledge(
        knowledge_type="lesson",
        title="Lesson 1",
        content="Do not chase gap-up",
        tags=["risk", "timing"],
    )
    assert lesson_payload["id"].startswith("l::")
    assert lesson_payload["entry_type"] == "lesson"

    rule_payload = service.ingest_knowledge(
        knowledge_type="rule",
        title="Rule",
        content="single loss < 2%",
        priority=10,
    )
    assert rule_payload["id"].startswith("r::")
    assert rule_payload["entry_type"] == "rule"

    assert service.delete_knowledge(entry_id="exists-id") is True
    assert service.delete_knowledge(entry_id="missing-id") is False
    assert fake_core.deleted_ids == ["exists-id", "missing-id"]


def test_strategy_service_memory_methods():
    class _FakeMemoryVaultDao:
        def __init__(self):
            self.tiers: dict[str, str] = {}
            self.forgotten: set[str] = set()

        def get_overrides(self):
            return {"tiers": dict(self.tiers), "forgotten": sorted(self.forgotten), "updated_at": 1.0}

        def set_tier(self, *, entry_id: str, tier: str):
            self.tiers[entry_id] = tier
            self.forgotten.discard(entry_id)
            return {"id": entry_id, "tier": tier}

        def forget(self, *, entry_id: str):
            self.tiers.pop(entry_id, None)
            self.forgotten.add(entry_id)
            return {"id": entry_id, "forgotten": True}

    dao = _FakeMemoryVaultDao()
    service = StrategyService(strategy_store=_FakeStore(), backtest_runner=_FakeRunner(), memory_vault_dao=dao)

    promote_payload = service.promote_memory(entry_id="m-1", current_tier="WARM")
    assert promote_payload == {"id": "m-1", "tier": "HOT"}

    demote_payload = service.demote_memory(entry_id="m-1", current_tier="HOT")
    assert demote_payload == {"id": "m-1", "tier": "WARM"}

    forget_payload = service.forget_memory(entry_id="m-1")
    assert forget_payload == {"id": "m-1", "forgotten": True}

    overrides = service.get_memory_overrides()
    assert overrides["tiers"] == {}
    assert overrides["forgotten"] == ["m-1"]
