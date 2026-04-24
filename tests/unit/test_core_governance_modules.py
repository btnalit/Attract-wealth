from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from src.core.coordinator import AgentCoordinator
from src.core.cost_tracker import CostTracker
from src.core.hooks import HookManager
from src.core.permissions import PermissionGuard
from src.core.tool_registry import ToolRegistry
from src.core.trading_vm import TradingVM


def test_permission_guard_tool_and_path_checks():
    guard = PermissionGuard(
        allowed_tools={"echo", "market_*"},
        blocked_tools={"forbidden", "debug_*"},
        allowed_path_prefixes=(r"D:\workspace",),
        blocked_path_prefixes=(r"D:\workspace\secret",),
        default_mode="allow",
    )
    allow = guard.check_tool("market_quote", actor="unit")
    deny_by_allowlist = guard.check_tool("not-registered", actor="unit")
    deny_blocked = guard.check_tool("debug_tool", actor="unit")

    assert allow.allowed is True
    assert allow.reason == "allowed_tool_pattern"
    assert deny_by_allowlist.allowed is False
    assert deny_by_allowlist.reason == "not_in_allowed_tools"
    assert deny_blocked.allowed is False
    assert deny_blocked.reason == "blocked_tool_pattern"

    path_allow = guard.check_path(r"D:\workspace\project\file.txt")
    path_blocked = guard.check_path(r"D:\workspace\secret\key.txt")
    path_deny = guard.check_path(r"D:\other\project\file.txt")
    assert path_allow.allowed is True
    assert path_allow.reason == "allowed_path_prefix"
    assert path_blocked.allowed is False
    assert path_blocked.reason == "blocked_path_prefix"
    assert path_deny.allowed is False
    assert path_deny.reason == "path_not_in_allowlist"


def test_permission_guard_default_deny_mode_for_tool_and_path():
    guard = PermissionGuard(default_mode="deny")
    tool_decision = guard.check_tool("echo")
    path_decision = guard.check_path(r"D:\workspace\project\file.txt")
    assert tool_decision.allowed is False
    assert tool_decision.reason == "default_deny_mode"
    assert path_decision.allowed is False
    assert path_decision.reason == "default_deny_mode"


def test_hook_manager_runs_sync_and_async_handlers():
    hook = HookManager()
    events: list[str] = []

    def _sync_handler(payload: dict):
        events.append(f"sync:{payload.get('value')}")

    async def _async_handler(payload: dict):
        await asyncio.sleep(0)
        events.append(f"async:{payload.get('value')}")

    hook.register("tool_pre", _sync_handler, name="sync_handler")
    hook.register("tool_pre", _async_handler, name="async_handler")
    emitted = asyncio.run(hook.emit("tool_pre", {"value": "ok"}))

    assert len(emitted) == 2
    assert events == ["sync:ok", "async:ok"]
    snapshot = hook.snapshot()
    assert snapshot["events_total"] == 2
    assert snapshot["errors_total"] == 0


def test_tool_registry_enforces_permission_and_records_stats():
    class EchoInput(BaseModel):
        value: str = Field(min_length=1)

    guard = PermissionGuard(allowed_tools={"echo"}, blocked_tools=set())
    hook = HookManager()
    phases: list[str] = []

    def _record_phase(payload: dict):
        phases.append(str(payload.get("tool", "")))

    hook.register("tool_pre", _record_phase, name="pre")
    hook.register("tool_post", _record_phase, name="post")
    registry = ToolRegistry(permission_guard=guard, hook_manager=hook)

    def _echo(payload: dict):
        return {"echo": payload.get("value", "")}

    registry.register(
        name="echo",
        handler=_echo,
        description="echo payload",
        input_model=EchoInput,
        example_payload={"value": "hello"},
    )
    result = asyncio.run(registry.execute("echo", {"value": "hello"}, actor="tester"))
    assert result["echo"] == "hello"
    assert phases == ["echo", "echo"]

    try:
        asyncio.run(registry.execute("echo", {"value": ""}, actor="tester"))
    except ValueError:
        validation_failed = True
    else:
        validation_failed = False
    assert validation_failed is True

    registry.register(name="forbidden", handler=_echo, description="forbidden payload")
    try:
        asyncio.run(registry.execute("forbidden", {"value": "nope"}, actor="tester"))
    except PermissionError:
        denied = True
    else:
        denied = False
    assert denied is True

    snapshot = registry.snapshot()
    echo_tool = next(item for item in snapshot["tools"] if item["name"] == "echo")
    assert "properties" in echo_tool["input_schema"]
    assert echo_tool["stats"]["calls"] == 2
    assert echo_tool["stats"]["success"] == 1
    assert echo_tool["stats"]["failed"] == 1


def test_coordinator_run_batch_captures_ok_error_timeout():
    coordinator = AgentCoordinator()

    async def _worker(value: int):
        if value == 2:
            raise RuntimeError("boom")
        if value == 3:
            await asyncio.sleep(0.05)
            return "slow"
        return value * 10

    result = asyncio.run(
        coordinator.run_batch(
            [1, 2, 3],
            _worker,
            max_concurrency=3,
            timeout_s=0.01,
        )
    )
    statuses = [item["status"] for item in result]
    assert statuses == ["ok", "error", "timeout"]

    snapshot = coordinator.snapshot()
    assert snapshot["runs"] == 1
    assert snapshot["tasks_total"] == 3
    assert snapshot["ok"] == 1
    assert snapshot["error"] == 1
    assert snapshot["timeout"] == 1


def test_cost_tracker_budget_status(monkeypatch):
    monkeypatch.setattr(
        "src.core.cost_tracker.TradingLedger.get_llm_usage_summary",
        lambda **kwargs: {"cost_usd": 1.2, "call_count": 2, "total_tokens": 3000},
    )
    tracker = CostTracker()
    status = tracker.daily_budget_status(daily_budget_usd=1.5, current_call_cost=0.4, hours=24)

    assert status["current_cost_usd"] == 1.2
    assert status["projected_cost_usd"] == 1.6
    assert status["exceeded"] is True


def test_trading_vm_governance_snapshot_contains_graph_topology():
    vm = TradingVM()
    snapshot = vm.get_governance_snapshot()
    assert "graph" in snapshot
    assert int(snapshot["graph"]["node_count"]) >= 1
    assert int(snapshot["graph"]["edge_count"]) >= 1
    assert snapshot["summary"]["graph_nodes"] == snapshot["graph"]["node_count"]
    assert snapshot["summary"]["graph_edges"] == snapshot["graph"]["edge_count"]
