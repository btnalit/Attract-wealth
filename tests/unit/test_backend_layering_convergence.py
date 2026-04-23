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


def test_strategy_service_encapsulates_store_and_backtest_runner() -> None:
    strategy_service_path = PROJECT_ROOT / "src" / "services" / "strategy_service.py"
    content = _read(strategy_service_path)

    assert "class StrategyService" in content
    assert "from src.core.strategy_store import StrategyStore" in content
    assert "from src.evolution.backtest_runner import BacktestRunner" in content
    assert "def run_backtest" in content
