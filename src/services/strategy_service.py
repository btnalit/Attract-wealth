"""Strategy domain service: encapsulate strategy router data access and backtest execution."""
from __future__ import annotations

from typing import Any

from src.core.strategy_store import StrategyStore
from src.evolution.backtest_runner import BacktestRunner


class StrategyService:
    """Service layer for strategy APIs."""

    _REQUIRED_STORE_METHODS = {
        "create_strategy_version",
        "list_strategy_versions",
        "get_strategy",
        "update_strategy_metrics",
        "evaluate_version_gate",
        "promote_strategy_version",
        "transition_strategy_status",
        "archive_backtest_report",
        "list_backtest_reports",
        "get_backtest_report",
    }

    def __init__(self, strategy_store: Any | None = None, backtest_runner: Any | None = None):
        self._store = strategy_store if self._is_valid_store(strategy_store) else None
        self._runner = backtest_runner if self._is_valid_runner(backtest_runner) else None

    @classmethod
    def _is_valid_store(cls, store: Any) -> bool:
        return bool(store is not None and all(hasattr(store, name) for name in cls._REQUIRED_STORE_METHODS))

    @staticmethod
    def _is_valid_runner(runner: Any) -> bool:
        return bool(runner is not None and hasattr(runner, "run"))

    def sync_dependencies(self, strategy_store: Any | None = None, backtest_runner: Any | None = None) -> None:
        """Sync optional dependencies from app state."""
        if self._is_valid_store(strategy_store):
            self._store = strategy_store
        if self._is_valid_runner(backtest_runner):
            self._runner = backtest_runner

    def _ensure_store(self):
        if not self._is_valid_store(self._store):
            self._store = StrategyStore()
        return self._store

    def _ensure_runner(self):
        if not self._is_valid_runner(self._runner):
            self._runner = BacktestRunner()
        return self._runner

    def create_strategy_version(self, **kwargs):
        return self._ensure_store().create_strategy_version(**kwargs)

    def list_strategy_versions(self, **kwargs):
        return self._ensure_store().list_strategy_versions(**kwargs)

    def get_strategy(self, strategy_id: str):
        return self._ensure_store().get_strategy(strategy_id)

    def update_strategy_metrics(self, strategy_id: str, metrics: dict[str, Any], *, merge: bool = True):
        return self._ensure_store().update_strategy_metrics(strategy_id, metrics, merge=merge)

    def evaluate_version_gate(self, strategy_id: str, **kwargs):
        return self._ensure_store().evaluate_version_gate(strategy_id, **kwargs)

    def promote_strategy_version(self, strategy_id: str, **kwargs):
        return self._ensure_store().promote_strategy_version(strategy_id, **kwargs)

    def transition_strategy_status(self, strategy_id: str, **kwargs):
        return self._ensure_store().transition_strategy_status(strategy_id, **kwargs)

    def archive_backtest_report(self, **kwargs):
        return self._ensure_store().archive_backtest_report(**kwargs)

    def list_backtest_reports(self, **kwargs):
        return self._ensure_store().list_backtest_reports(**kwargs)

    def get_backtest_report(self, report_id: str):
        return self._ensure_store().get_backtest_report(report_id)

    def run_backtest(self, **kwargs):
        return self._ensure_runner().run(**kwargs)
