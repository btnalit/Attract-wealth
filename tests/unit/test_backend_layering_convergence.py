from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_strategy_router_uses_service_layer_instead_of_store_runner_direct_imports() -> None:
    strategy_router_path = PROJECT_ROOT / "src" / "routers" / "strategy.py"
    content = _read(strategy_router_path)

    assert "from src.services.strategy_service import StrategyService" in content
    assert "from src.core.strategy_store import StrategyStore" not in content
    assert "from src.evolution.backtest_runner import BacktestRunner" not in content
    assert "strategy_service.list_strategy_history" in content


def test_strategy_service_encapsulates_store_and_backtest_runner() -> None:
    strategy_service_path = PROJECT_ROOT / "src" / "services" / "strategy_service.py"
    content = _read(strategy_service_path)

    assert "class StrategyService" in content
    assert "from src.core.strategy_store import StrategyStore" in content
    assert "from src.evolution.backtest_runner import BacktestRunner" in content
    assert "def run_backtest" in content


def test_strategy_memory_actions_use_service_and_dao_layers() -> None:
    strategy_service_path = PROJECT_ROOT / "src" / "services" / "strategy_service.py"
    service_content = _read(strategy_service_path)
    assert "from src.dao.memory_vault_dao import MemoryVaultDAO" in service_content
    assert "def get_memory_overrides" in service_content
    assert "def promote_memory" in service_content
    assert "def demote_memory" in service_content
    assert "def forget_memory" in service_content

    strategy_router_path = PROJECT_ROOT / "src" / "routers" / "strategy.py"
    router_content = _read(strategy_router_path)
    assert "@router.get(\"/memory/overrides\")" in router_content
    assert "@router.post(\"/memory/promote\")" in router_content
    assert "@router.post(\"/memory/demote\")" in router_content
    assert "@router.post(\"/memory/forget\")" in router_content
    assert "strategy_service.promote_memory" in router_content
    assert "strategy_service.demote_memory" in router_content
    assert "strategy_service.forget_memory" in router_content


def test_monitor_router_uses_service_layer_without_db_direct_access() -> None:
    monitor_router_path = PROJECT_ROOT / "src" / "routers" / "monitor.py"
    content = _read(monitor_router_path)

    assert "from src.services.monitor_service import MonitorService" in content
    assert "from src.core.storage import get_main_db" not in content
    assert "from src.core.storage import get_ledger_db" not in content
    assert "from src.core.trading_ledger import TradingLedger" not in content


def test_monitor_service_uses_monitor_dao_for_db_aggregation() -> None:
    monitor_service_path = PROJECT_ROOT / "src" / "services" / "monitor_service.py"
    content = _read(monitor_service_path)

    assert "from src.dao.monitor_dao import MonitorDAO" in content
    assert "class MonitorService" in content
    assert "def __init__(self, trading_service: Any, monitor_dao: MonitorDAO | None = None)" in content


def test_system_router_uses_ths_diagnosis_service_for_host_diag() -> None:
    system_router_path = PROJECT_ROOT / "src" / "routers" / "system.py"
    content = _read(system_router_path)

    assert "from src.services.ths_diagnosis_service import THSDiagnosisService" in content
    assert "from src.services.system_query_service import SystemQueryService" in content
    assert "def _get_ths_diagnosis_service(request: Request) -> THSDiagnosisService" in content
    assert "def _get_system_query_service(request: Request) -> SystemQueryService" in content
    assert "@router.get(\"/ths-host/diagnosis\")" in content
    assert "from src.core.trading_ledger import TradingLedger" not in content


def test_core_governance_modules_are_present_and_runtime_connected() -> None:
    core_dir = PROJECT_ROOT / "src" / "core"
    required = [
        core_dir / "permissions.py",
        core_dir / "hooks.py",
        core_dir / "tool_registry.py",
        core_dir / "coordinator.py",
        core_dir / "cost_tracker.py",
    ]
    for path in required:
        assert path.exists(), f"missing governance module: {path.name}"

    vm_content = _read(core_dir / "trading_vm.py")
    assert "PermissionGuard.from_env()" in vm_content
    assert "ToolRegistry(" in vm_content
    assert "def get_governance_snapshot(self) -> dict[str, Any]:" in vm_content
    assert "from src.core.agent_state import AgentState" in vm_content
    assert "from src.routers.stream import" not in vm_content
    assert "event_publisher" in vm_content

    service_content = _read(core_dir / "trading_service.py")
    assert "\"core_governance\": governance_snapshot" in service_content

    system_router_content = _read(PROJECT_ROOT / "src" / "routers" / "system.py")
    assert "\"core_governance\": service_runtime.get(\"core_governance\", {})" in system_router_content


def test_graph_modules_are_split_and_state_contract_is_decoupled() -> None:
    graph_dir = PROJECT_ROOT / "src" / "graph"
    required_graph_modules = [
        graph_dir / "trading_graph.py",
        graph_dir / "signal_processing.py",
        graph_dir / "conditional_logic.py",
        graph_dir / "reflection.py",
    ]
    for path in required_graph_modules:
        assert path.exists(), f"missing graph module: {path.name}"

    graph_content = _read(graph_dir / "trading_graph.py")
    assert "from src.graph.signal_processing import" in graph_content
    assert "from src.graph.conditional_logic import" in graph_content
    assert "from src.graph.reflection import" in graph_content
    assert "class TradingGraphAgents" in graph_content
    assert "def get_graph_topology() -> dict[str, Any]:" in graph_content

    agent_state_content = _read(PROJECT_ROOT / "src" / "core" / "agent_state.py")
    assert "class AgentState(TypedDict):" in agent_state_content

    vm_content = _read(PROJECT_ROOT / "src" / "core" / "trading_vm.py")
    assert "from src.core.agent_state import AgentState" in vm_content
    assert "class AgentState(TypedDict):" not in vm_content

    analyst_base = _read(PROJECT_ROOT / "src" / "agents" / "analysts" / "base.py")
    assert "from src.core.agent_state import AgentState" in analyst_base
    assert "from src.core.trading_vm import AgentState" not in analyst_base
