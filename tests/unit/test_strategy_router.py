from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.core.errors import TradingServiceError
from src.routers.strategy import router
from src.services.strategy_service import StrategyService


class _FakeStrategyStore:
    def __init__(self):
        self._items: dict[str, dict] = {}
        self._reports: dict[str, dict] = {}

    def create_strategy_version(self, **kwargs):
        sid = f"st-{len(self._items) + 1}"
        name = kwargs.get("name", "")
        existing = [item for item in self._items.values() if item.get("name") == name]
        params = dict(kwargs.get("parameters", {}))
        market = str(kwargs.get("market", params.get("market", "CN"))).upper()
        template = str(kwargs.get("strategy_template", params.get("strategy_template", "default"))).lower()
        params.setdefault("market", market)
        params.setdefault("strategy_template", template)
        row = {
            "id": sid,
            "name": name,
            "version": len(existing) + 1,
            "parent_id": kwargs.get("parent_id", ""),
            "origin": kwargs.get("origin", "BUILT_IN"),
            "content": kwargs.get("content", ""),
            "parameters": params,
            "metrics": dict(kwargs.get("metrics", {})),
            "status": kwargs.get("status", "draft"),
            "created_at": 1.0,
            "updated_at": 1.0,
        }
        self._items[sid] = row
        return dict(row)

    def list_strategy_versions(self, *, name: str = "", status: str = "", limit: int = 50):
        rows = list(self._items.values())
        if name:
            rows = [item for item in rows if item["name"] == name]
        if status:
            rows = [item for item in rows if item["status"] == status]
        return rows[:limit]

    def get_strategy(self, strategy_id: str):
        row = self._items.get(strategy_id)
        if not row:
            raise TradingServiceError("STRATEGY_NOT_FOUND", "not found", {"strategy_id": strategy_id}, 404)
        return dict(row)

    def update_strategy_metrics(self, strategy_id: str, metrics: dict, *, merge: bool = True):
        row = self.get_strategy(strategy_id)
        if merge:
            row["metrics"] = {**row.get("metrics", {}), **metrics}
        else:
            row["metrics"] = dict(metrics)
        self._items[strategy_id] = row
        return dict(row)

    def evaluate_version_gate(
        self,
        strategy_id: str,
        *,
        metrics=None,
        overrides=None,
        persist: bool = True,
        market: str = "",
        strategy_template: str = "",
    ):
        row = self.get_strategy(strategy_id)
        values = dict(metrics or row.get("metrics", {}))
        min_win_rate = float((overrides or {}).get("min_win_rate", 0.5))
        passed = float(values.get("win_rate", 0.0)) >= min_win_rate
        result = {
            "strategy_id": strategy_id,
            "strategy_name": row["name"],
            "version": row["version"],
            "passed": passed,
            "checks": [{"metric": "win_rate", "passed": passed}],
            "failed_checks": [] if passed else [{"metric": "win_rate"}],
            "gate": {"min_win_rate": min_win_rate},
            "metrics": values,
            "gate_context": {
                "market": market or values.get("market", row["parameters"].get("market", "CN")),
                "strategy_template": strategy_template
                or values.get("strategy_template", row["parameters"].get("strategy_template", "default")),
                "rule_sources": [{"source": "fake.default", "rules": {"min_win_rate": min_win_rate}}],
                "manual_overrides": {"min_win_rate": min_win_rate} if (overrides or {}).get("min_win_rate") else {},
            },
        }
        if persist:
            self.update_strategy_metrics(strategy_id, {"version_gate": result}, merge=True)
        return result

    def transition_strategy_status(
        self,
        strategy_id: str,
        *,
        target_status: str,
        operator: str = "api",
        force: bool = False,
        gate_result=None,
        gate_overrides=None,
        market: str = "",
        strategy_template: str = "",
    ):
        row = self.get_strategy(strategy_id)
        from_status = row.get("status", "draft")
        to_status = str(target_status or "").strip().lower()
        if to_status not in {"candidate", "active", "retired", "rejected", "draft"}:
            raise TradingServiceError("INVALID_STRATEGY_REQUEST", "invalid target", {"target_status": target_status}, 400)
        if not force and to_status in {"candidate", "active"}:
            gate = gate_result or self.evaluate_version_gate(
                strategy_id,
                overrides=dict(gate_overrides or {}),
                persist=True,
                market=market,
                strategy_template=strategy_template,
            )
            if not gate.get("passed", False):
                raise TradingServiceError("STRATEGY_VERSION_GATE_FAILED", "gate failed", {"strategy_id": strategy_id}, 409)
        row["status"] = to_status
        self._items[strategy_id] = row
        return {
            "strategy": dict(row),
            "from_status": from_status,
            "to_status": to_status,
            "operator": operator,
            "force": force,
            "gate": gate_result or {},
            "demoted_ids": [],
        }

    def promote_strategy_version(
        self,
        strategy_id: str,
        *,
        operator: str = "api",
        force: bool = False,
        gate_result=None,
        gate_overrides=None,
        market: str = "",
        strategy_template: str = "",
    ):
        return self.transition_strategy_status(
            strategy_id,
            target_status="active",
            operator=operator,
            force=force,
            gate_result=gate_result,
            gate_overrides=gate_overrides,
            market=market,
            strategy_template=strategy_template,
        )

    def archive_backtest_report(self, **kwargs):
        rid = f"rp-{len(self._reports) + 1}"
        strategy = self.get_strategy(kwargs.get("strategy_id", ""))
        report = dict(kwargs.get("report", {}))
        record = {
            "id": rid,
            "strategy_id": strategy["id"],
            "strategy_name": strategy["name"],
            "strategy_version": strategy["version"],
            "market": kwargs.get("market", "CN"),
            "strategy_template": kwargs.get("strategy_template", "default"),
            "run_tag": kwargs.get("run_tag", ""),
            "source": kwargs.get("source", "api"),
            "bars_hash": kwargs.get("bars_hash", ""),
            "params_hash": kwargs.get("params_hash", ""),
            "metrics": dict(report.get("metrics", {})),
            "summary": dict(report.get("summary", {})),
            "trace_index": {"report_id": rid},
            "created_at": 1.0,
            "report_payload": {"backtest": report},
        }
        self._reports[rid] = record
        return dict(record)

    def list_backtest_reports(
        self,
        *,
        strategy_id: str = "",
        strategy_name: str = "",
        market: str = "",
        strategy_template: str = "",
        run_tag: str = "",
        limit: int = 50,
    ):
        rows = list(self._reports.values())
        if strategy_id:
            rows = [row for row in rows if row["strategy_id"] == strategy_id]
        if strategy_name:
            rows = [row for row in rows if row["strategy_name"] == strategy_name]
        if market:
            rows = [row for row in rows if row["market"] == market]
        if strategy_template:
            rows = [row for row in rows if row["strategy_template"] == strategy_template]
        if run_tag:
            rows = [row for row in rows if row["run_tag"] == run_tag]
        return [dict(row) for row in rows[:limit]]

    def get_backtest_report(self, report_id: str):
        row = self._reports.get(report_id)
        if not row:
            raise TradingServiceError("STRATEGY_BACKTEST_REPORT_NOT_FOUND", "not found", {"report_id": report_id}, 404)
        return dict(row)


class _FakeBacktestRunner:
    def run(self, **kwargs):
        params = dict(kwargs.get("parameters", {}))
        lookback = float(params.get("lookback", 3))
        position_ratio = float(params.get("position_ratio", 0.5))
        win_rate = min(0.95, max(0.2, 0.5 + (position_ratio - 0.5) * 0.2))
        net_pnl = 1000.0 + lookback * 200.0 + position_ratio * 500.0
        sharpe = 0.6 + lookback * 0.05
        return {
            "strategy": {"id": kwargs.get("strategy_id", ""), "name": kwargs.get("strategy_name", ""), "version": 1},
            "params": {},
            "metrics": {
                "trade_count": 30,
                "win_rate": round(win_rate, 6),
                "max_drawdown": 0.1,
                "net_pnl": round(net_pnl, 6),
                "sharpe": round(sharpe, 6),
            },
            "summary": {"bars": len(kwargs.get("bars", []))},
            "trades": [],
            "equity_curve_tail": [],
        }


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


def _build_client() -> TestClient:
    app = FastAPI()
    app.state.strategy_store = _FakeStrategyStore()
    app.state.backtest_runner = _FakeBacktestRunner()
    app.state.memory_vault_dao = _FakeMemoryVaultDao()
    app.include_router(router, prefix="/api/strategy")
    return TestClient(app)


def test_strategy_router_create_list_backtest_gate_promote_success():
    client = _build_client()
    create_resp = client.post(
        "/api/strategy/versions",
        json={
            "name": "demo",
            "parameters": {"lookback": 3},
            "metrics": {"win_rate": 0.61, "trade_count": 30, "max_drawdown": 0.1, "net_pnl": 1000, "sharpe": 1.0},
            "status": "candidate",
            "market": "CN",
            "strategy_template": "momentum",
        },
    )
    assert create_resp.status_code == 200
    strategy_id = create_resp.json()["data"]["id"]

    list_resp = client.get("/api/strategy/versions", params={"name": "demo"})
    assert list_resp.status_code == 200
    assert list_resp.json()["data"]["count"] == 1

    backtest_resp = client.post(
        "/api/strategy/backtest",
        json={
            "strategy_id": strategy_id,
            "bars": [
                {"ts": "2026-01-01", "close": 10.0},
                {"ts": "2026-01-02", "close": 10.5},
                {"ts": "2026-01-03", "close": 10.8},
            ],
            "market": "CN",
            "strategy_template": "momentum",
            "run_tag": "nightly",
            "persist_metrics": True,
            "archive_report": True,
        },
    )
    assert backtest_resp.status_code == 200
    assert backtest_resp.json()["code"] == "STRATEGY_BACKTEST_OK"
    report_id = backtest_resp.json()["data"]["archive"]["id"]

    list_reports_resp = client.get("/api/strategy/backtests", params={"strategy_id": strategy_id})
    assert list_reports_resp.status_code == 200
    assert list_reports_resp.json()["data"]["count"] == 1

    report_detail_resp = client.get(f"/api/strategy/backtests/{report_id}")
    assert report_detail_resp.status_code == 200
    assert report_detail_resp.json()["data"]["id"] == report_id

    gate_resp = client.post(
        f"/api/strategy/versions/{strategy_id}/gate",
        json={"min_win_rate": 0.5, "market": "CN", "strategy_template": "momentum"},
    )
    assert gate_resp.status_code == 200
    assert gate_resp.json()["code"] == "STRATEGY_GATE_PASSED"

    promote_resp = client.post(f"/api/strategy/versions/{strategy_id}/promote", json={"operator": "unit"})
    assert promote_resp.status_code == 200
    assert promote_resp.json()["code"] == "STRATEGY_PROMOTED"
    assert promote_resp.json()["data"]["strategy"]["status"] == "active"


def test_strategy_router_transition_and_grid_backtest():
    client = _build_client()
    create_resp = client.post(
        "/api/strategy/versions",
        json={
            "name": "grid_demo",
            "metrics": {"trade_count": 40, "win_rate": 0.65, "max_drawdown": 0.12, "net_pnl": 1200, "sharpe": 1.1},
            "status": "draft",
            "parameters": {"lookback": 3, "position_ratio": 0.5},
            "market": "CN",
            "strategy_template": "momentum",
        },
    )
    strategy_id = create_resp.json()["data"]["id"]

    transition_candidate = client.post(
        f"/api/strategy/versions/{strategy_id}/transition",
        json={"target_status": "candidate", "operator": "unit"},
    )
    assert transition_candidate.status_code == 200
    assert transition_candidate.json()["data"]["strategy"]["status"] == "candidate"

    grid_resp = client.post(
        "/api/strategy/backtest/grid",
        json={
            "strategy_id": strategy_id,
            "bars": [
                {"ts": "2026-01-01", "close": 10.0},
                {"ts": "2026-01-02", "close": 10.2},
                {"ts": "2026-01-03", "close": 10.4},
            ],
            "parameter_grid": {"lookback": [2, 4], "position_ratio": [0.4, 0.8]},
            "sort_by": "net_pnl",
            "top_k": 2,
            "run_tag": "grid_batch",
            "archive_report": True,
            "evaluate_gate": True,
            "persist_best_metrics": True,
        },
    )
    assert grid_resp.status_code == 200
    body = grid_resp.json()
    assert body["code"] == "STRATEGY_BACKTEST_GRID_OK"
    assert body["data"]["summary"]["total_runs"] == 4
    assert len(body["data"]["top_results"]) == 2
    assert body["data"]["best"]["metrics"]["net_pnl"] >= body["data"]["top_results"][1]["metrics"]["net_pnl"]

    transition_active = client.post(
        f"/api/strategy/versions/{strategy_id}/transition",
        json={"target_status": "active", "operator": "unit"},
    )
    assert transition_active.status_code == 200
    assert transition_active.json()["data"]["strategy"]["status"] == "active"


def test_strategy_router_promote_rejected_when_gate_failed():
    client = _build_client()
    create_resp = client.post(
        "/api/strategy/versions",
        json={"name": "demo", "metrics": {"win_rate": 0.2}, "status": "candidate"},
    )
    strategy_id = create_resp.json()["data"]["id"]

    resp = client.post(
        f"/api/strategy/versions/{strategy_id}/promote",
        json={"operator": "unit", "run_gate": True, "gate_overrides": {"min_win_rate": 0.9}},
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body["ok"] is False
    assert body["code"] == "STRATEGY_VERSION_GATE_FAILED"


def test_strategy_history_endpoint_returns_structured_ooda():
    client = _build_client()
    create_resp = client.post(
        "/api/strategy/versions",
        json={
            "name": "history_demo",
            "origin": "MUTATION",
            "metrics": {
                "trade_count": 36,
                "win_rate": 0.63,
                "max_drawdown": 0.11,
                "net_pnl": 1888,
                "sharpe": 1.02,
            },
            "status": "candidate",
        },
    )
    assert create_resp.status_code == 200

    history_resp = client.get("/api/strategy/history", params={"limit": 20})
    assert history_resp.status_code == 200
    body = history_resp.json()
    assert body["ok"] is True
    assert isinstance(body["data"], list)
    assert len(body["data"]) >= 1
    event = body["data"][0]
    assert event["type"] == "MUTATION"
    assert isinstance(event["ooda"], dict)
    assert set(event["ooda"].keys()) >= {"observe", "orient", "decide", "act", "trades", "pnl", "deviations"}
    assert "win rate" in event["ooda"]["orient"]


def test_strategy_version_diff_endpoint_with_parent_baseline():
    client = _build_client()
    base_resp = client.post(
        "/api/strategy/versions",
        json={
            "name": "diff_demo",
            "content": '{"entry_signal":"ma_cross","risk_limit":0.2,"bias":"long"}',
            "parameters": {"lookback": 3, "position_ratio": 0.5},
            "metrics": {
                "trade_count": 20,
                "win_rate": 0.55,
                "max_drawdown": 0.12,
                "net_pnl": 1200,
                "sharpe": 0.9,
            },
            "status": "candidate",
        },
    )
    assert base_resp.status_code == 200
    base_id = base_resp.json()["data"]["id"]

    child_resp = client.post(
        "/api/strategy/versions",
        json={
            "name": "diff_demo",
            "parent_id": base_id,
            "content": '{"entry_signal":"ma_cross","risk_limit":0.15,"bias":"long","rebalance":"weekly"}',
            "parameters": {"lookback": 5, "position_ratio": 0.7},
            "metrics": {
                "trade_count": 35,
                "win_rate": 0.62,
                "max_drawdown": 0.1,
                "net_pnl": 1900,
                "sharpe": 1.2,
            },
            "status": "candidate",
        },
    )
    assert child_resp.status_code == 200
    child_id = child_resp.json()["data"]["id"]

    bars = [
        {"ts": "2026-01-01", "close": 10.0},
        {"ts": "2026-01-02", "close": 10.4},
        {"ts": "2026-01-03", "close": 10.7},
    ]
    base_backtest_resp = client.post("/api/strategy/backtest", json={"strategy_id": base_id, "bars": bars})
    assert base_backtest_resp.status_code == 200
    child_backtest_resp = client.post("/api/strategy/backtest", json={"strategy_id": child_id, "bars": bars})
    assert child_backtest_resp.status_code == 200
    base_report_id = base_backtest_resp.json()["data"]["archive"]["id"]
    child_report_id = child_backtest_resp.json()["data"]["archive"]["id"]

    diff_resp = client.get(f"/api/strategy/versions/{child_id}/diff")
    assert diff_resp.status_code == 200
    body = diff_resp.json()
    assert body["ok"] is True
    assert body["code"] == "STRATEGY_VERSION_DIFF_OK"
    assert body["data"]["has_baseline"] is True
    assert body["data"]["baseline_source"] == "parent"
    assert body["data"]["baseline"]["id"] == base_id
    assert body["data"]["metric_diff"]["trade_count"]["delta"] == 0.0
    assert body["data"]["metric_diff"]["net_pnl"]["delta"] > 0
    assert "lookback" in body["data"]["parameter_diff"]["changed"]
    assert body["data"]["content_changed"] is True
    assert body["data"]["content_diff"]["mode"] == "json_fields"
    assert body["data"]["content_diff"]["changed"] is True
    assert body["data"]["content_diff"]["summary"]["changed_fields"] >= 1
    assert body["data"]["content_diff"]["summary"]["added_fields"] >= 1
    assert body["data"]["backtest_compare"]["compare_ready"] is True
    assert body["data"]["backtest_compare"]["current_report_id"] == child_report_id
    assert body["data"]["backtest_compare"]["baseline_report_id"] == base_report_id
    assert "/backtest?compareA=" in body["data"]["backtest_compare"]["compare_page_url"]


def test_strategy_knowledge_endpoint_returns_normalized_items(monkeypatch):
    class _FakeKnowledgeCore:
        def search_patterns(self, _query: str, _top_k: int):
            return [
                {
                    "id": "p-1",
                    "name": "Breakout",
                    "description": "Price breaks resistance with volume",
                    "tags": '["pattern","volume"]',
                    "relevance_score": 0.86,
                    "vector": [0.75, 0.25],
                }
            ]

        def search_lessons(self, _query: str, _top_k: int):
            return []

        def search_rules(self, _query: str, _top_k: int):
            return []

        def search_all(self, _query: str, _top_k: int):
            return {"patterns": [], "lessons": [], "rules": []}

        def add_pattern(self, name: str, description: str, context: dict):
            return f"p::{name}::{description}::{context.get('source', '')}"

        def add_lesson(self, title: str, content: str, tags: list[str]):
            return f"l::{title}::{content}::{len(tags)}"

        def add_expert_rule(self, rule_text: str, priority: int = 0):
            return f"r::{rule_text}::{priority}"

        def delete_entry(self, entry_id: str):
            return entry_id == "p-1"

    monkeypatch.setattr(StrategyService, "_create_knowledge_core", lambda self: _FakeKnowledgeCore())
    client = _build_client()
    resp = client.get("/api/strategy/knowledge", params={"type": "patterns", "q": "breakout", "top_k": 5})
    assert resp.status_code == 200

    body = resp.json()
    assert body["ok"] is True
    assert body["code"] == "KNOWLEDGE_SEARCH_OK"
    assert isinstance(body["data"], list)
    assert len(body["data"]) == 1
    item = body["data"][0]
    assert item["id"] == "p-1"
    assert item["type"] == "Pattern"
    assert item["title"] == "Breakout"
    assert item["relevance"] == 86.0
    assert item["memory_tier"] == "HOT"
    assert item["tags"] == ["pattern", "volume"]
    assert isinstance(item["vector"], list)
    assert len(item["vector"]) == 2
    assert item["summary"]
    assert item["fullContent"]

    ingest_resp = client.post(
        "/api/strategy/knowledge/ingest",
        json={
            "type": "pattern",
            "title": "Breakout",
            "content": "Price breaks resistance with volume",
            "tags": ["pattern", "volume"],
            "context": {"source": "unit_test"},
        },
    )
    assert ingest_resp.status_code == 200
    ingest_body = ingest_resp.json()
    assert ingest_body["ok"] is True
    assert ingest_body["code"] == "KNOWLEDGE_INGEST_OK"
    assert ingest_body["data"]["entry_type"] == "pattern"
    assert ingest_body["data"]["id"].startswith("p::")

    delete_resp = client.post("/api/strategy/knowledge/delete", json={"id": "p-1"})
    assert delete_resp.status_code == 200
    delete_body = delete_resp.json()
    assert delete_body["ok"] is True
    assert delete_body["code"] == "KNOWLEDGE_DELETE_OK"
    assert delete_body["data"]["deleted"] is True


def test_strategy_knowledge_endpoint_does_not_generate_fake_vector(monkeypatch):
    class _FakeKnowledgeCoreNoVector:
        def search_patterns(self, _query: str, _top_k: int):
            return [{"id": "p-novec", "name": "NoVec", "description": "No vector payload", "relevance_score": 0.73}]

        def search_lessons(self, _query: str, _top_k: int):
            return []

        def search_rules(self, _query: str, _top_k: int):
            return []

        def search_all(self, _query: str, _top_k: int):
            return {"patterns": [], "lessons": [], "rules": []}

        def add_pattern(self, name: str, description: str, context: dict):
            return f"p::{name}::{description}::{context.get('source', '')}"

        def add_lesson(self, title: str, content: str, tags: list[str]):
            return f"l::{title}::{content}::{len(tags)}"

        def add_expert_rule(self, rule_text: str, priority: int = 0):
            return f"r::{rule_text}::{priority}"

        def delete_entry(self, entry_id: str):
            return entry_id == "p-novec"

    monkeypatch.setattr(StrategyService, "_create_knowledge_core", lambda self: _FakeKnowledgeCoreNoVector())
    client = _build_client()
    resp = client.get("/api/strategy/knowledge", params={"type": "patterns", "q": "novec", "top_k": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert len(body["data"]) == 1
    assert body["data"][0]["id"] == "p-novec"
    assert body["data"][0]["vector"] is None
    assert body["data"][0]["memory_tier"] == "WARM"


def test_strategy_knowledge_endpoint_degrades_to_empty_when_core_missing(monkeypatch):
    def _raise_import_error(_self):
        raise ImportError("knowledge core not available")

    monkeypatch.setattr(StrategyService, "_create_knowledge_core", _raise_import_error)
    client = _build_client()
    resp = client.get("/api/strategy/knowledge", params={"type": "rules", "q": "risk", "top_k": 3})
    assert resp.status_code == 200

    body = resp.json()
    assert body["ok"] is True
    assert body["code"] == "KNOWLEDGE_CORE_UNAVAILABLE"
    assert body["data"] == []

    ingest_resp = client.post(
        "/api/strategy/knowledge/ingest",
        json={"type": "rule", "title": "止损", "content": "单笔亏损超过2%立即平仓"},
    )
    assert ingest_resp.status_code == 503
    ingest_body = ingest_resp.json()
    assert ingest_body["ok"] is False
    assert ingest_body["code"] == "KNOWLEDGE_CORE_UNAVAILABLE"


def test_strategy_memory_override_endpoints_work() -> None:
    client = _build_client()

    initial_resp = client.get("/api/strategy/memory/overrides")
    assert initial_resp.status_code == 200
    initial_body = initial_resp.json()
    assert initial_body["ok"] is True
    assert initial_body["code"] == "MEMORY_OVERRIDES_OK"
    assert initial_body["data"]["tiers"] == {}
    assert initial_body["data"]["forgotten"] == []

    promote_resp = client.post(
        "/api/strategy/memory/promote",
        json={"id": "m-1", "current_tier": "WARM"},
    )
    assert promote_resp.status_code == 200
    promote_body = promote_resp.json()
    assert promote_body["ok"] is True
    assert promote_body["code"] == "MEMORY_PROMOTE_OK"
    assert promote_body["data"] == {"id": "m-1", "tier": "HOT"}

    demote_resp = client.post(
        "/api/strategy/memory/demote",
        json={"id": "m-1", "current_tier": "HOT"},
    )
    assert demote_resp.status_code == 200
    demote_body = demote_resp.json()
    assert demote_body["ok"] is True
    assert demote_body["code"] == "MEMORY_DEMOTE_OK"
    assert demote_body["data"] == {"id": "m-1", "tier": "WARM"}

    forget_resp = client.post("/api/strategy/memory/forget", json={"id": "m-1"})
    assert forget_resp.status_code == 200
    forget_body = forget_resp.json()
    assert forget_body["ok"] is True
    assert forget_body["code"] == "MEMORY_FORGET_OK"
    assert forget_body["data"] == {"id": "m-1", "forgotten": True}

    final_resp = client.get("/api/strategy/memory/overrides")
    assert final_resp.status_code == 200
    final_body = final_resp.json()
    assert final_body["data"]["tiers"] == {}
    assert final_body["data"]["forgotten"] == ["m-1"]

    invalid_tier_resp = client.post(
        "/api/strategy/memory/promote",
        json={"id": "m-2", "current_tier": "UNKNOWN"},
    )
    assert invalid_tier_resp.status_code == 400
    invalid_tier_body = invalid_tier_resp.json()
    assert invalid_tier_body["ok"] is False
    assert invalid_tier_body["code"] == "INVALID_STRATEGY_REQUEST"
