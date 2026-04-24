"""Strategy domain service: encapsulate strategy router data access and backtest execution."""
from __future__ import annotations

from typing import Any

from src.core.strategy_store import StrategyStore
from src.dao.memory_vault_dao import MemoryVaultDAO
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
    _REQUIRED_MEMORY_DAO_METHODS = {
        "get_overrides",
        "set_tier",
        "forget",
    }

    def __init__(
        self,
        strategy_store: Any | None = None,
        backtest_runner: Any | None = None,
        memory_vault_dao: Any | None = None,
    ):
        self._store = strategy_store if self._is_valid_store(strategy_store) else None
        self._runner = backtest_runner if self._is_valid_runner(backtest_runner) else None
        self._memory_vault_dao = memory_vault_dao if self._is_valid_memory_dao(memory_vault_dao) else None

    @staticmethod
    def _normalize_knowledge_type(value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in {"pattern", "lesson", "rule"}:
            return normalized
        return "rule"

    @staticmethod
    def _normalize_knowledge_tags(tags: list[str] | None) -> list[str]:
        if not isinstance(tags, list):
            return []
        return [str(item).strip() for item in tags if str(item).strip()]

    def _create_knowledge_core(self):
        from src.evolution.knowledge_core import KnowledgeCore

        return KnowledgeCore()

    @staticmethod
    def _normalize_memory_tier(value: str) -> str:
        tier = str(value or "").strip().upper()
        if tier in {"HOT", "WARM", "COLD"}:
            return tier
        raise ValueError("memory tier must be HOT/WARM/COLD")

    @staticmethod
    def _to_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _to_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @classmethod
    def _normalize_ratio(cls, value: Any) -> float:
        raw = cls._to_float(value, 0.0)
        if raw <= 0:
            return 0.0
        ratio = raw / 100.0 if raw > 1 else raw
        if ratio < 0:
            return 0.0
        if ratio > 1:
            return 1.0
        return ratio

    @staticmethod
    def _pick_value(metrics: dict[str, Any], *aliases: str) -> Any:
        for alias in aliases:
            if alias in metrics:
                return metrics.get(alias)
        return None

    @classmethod
    def _build_ooda_payload(
        cls,
        *,
        strategy_name: str,
        event_type: str,
        status: str,
        metrics: dict[str, Any],
    ) -> dict[str, Any]:
        trade_count = max(0, cls._to_int(cls._pick_value(metrics, "trade_count", "trades"), 0))
        win_rate = cls._normalize_ratio(cls._pick_value(metrics, "win_rate", "winRate"))
        drawdown = cls._normalize_ratio(cls._pick_value(metrics, "max_drawdown", "maxDrawdown"))
        sharpe = cls._to_float(cls._pick_value(metrics, "sharpe_ratio", "sharpe"), 0.0)
        net_pnl = cls._to_float(cls._pick_value(metrics, "net_pnl", "total_pnl"), 0.0)
        gate_payload = metrics.get("version_gate", {})
        gate_passed = bool(gate_payload.get("passed", False)) if isinstance(gate_payload, dict) else False

        deviations = 0
        if trade_count < 20:
            deviations += 1
        if win_rate < 0.5:
            deviations += 1
        if drawdown > 0.2:
            deviations += 1
        if sharpe < 0.5:
            deviations += 1

        strategy_label = strategy_name or "Unknown Strategy"
        observe = f"{strategy_label} {event_type} event observed, status={status.upper() or 'DRAFT'}."
        orient = f"win rate {win_rate * 100:.2f}% | max DD {drawdown * 100:.2f}% | sharpe {sharpe:.2f}"

        quality_ready = gate_passed or (trade_count >= 20 and win_rate >= 0.55 and drawdown <= 0.2 and sharpe >= 0.8)
        if trade_count <= 0:
            decide = "No valid trade samples, hold status transition."
            act = "Collect backtest samples before next review."
        elif drawdown > 0.2:
            decide = "Max drawdown breaches guardrail, prioritize risk remediation."
            act = "Keep non-active status and run parameter convergence."
        elif quality_ready:
            decide = "Core metrics satisfy gate baseline, move to transition review."
            act = (
                "Keep active status and monitor deviations."
                if str(status or "").strip().lower() == "active"
                else "Prepare candidate/active transition with operator approval."
            )
        elif win_rate >= 0.5 and drawdown <= 0.25:
            decide = "Metrics are near gate baseline, iterate with small parameter updates."
            act = "Run targeted backtest iteration and reassess."
        else:
            decide = "Current quality does not satisfy gate baseline."
            act = "Pause transition and continue strategy remediation."

        return {
            "observe": observe,
            "orient": orient,
            "decide": decide,
            "act": act,
            "trades": trade_count,
            "pnl": round(net_pnl, 6),
            "deviations": deviations,
        }

    @classmethod
    def _is_valid_store(cls, store: Any) -> bool:
        return bool(store is not None and all(hasattr(store, name) for name in cls._REQUIRED_STORE_METHODS))

    @staticmethod
    def _is_valid_runner(runner: Any) -> bool:
        return bool(runner is not None and hasattr(runner, "run"))

    @classmethod
    def _is_valid_memory_dao(cls, dao: Any) -> bool:
        return bool(dao is not None and all(hasattr(dao, name) for name in cls._REQUIRED_MEMORY_DAO_METHODS))

    def sync_dependencies(
        self,
        strategy_store: Any | None = None,
        backtest_runner: Any | None = None,
        memory_vault_dao: Any | None = None,
    ) -> None:
        """Sync optional dependencies from app state."""
        if self._is_valid_store(strategy_store):
            self._store = strategy_store
        if self._is_valid_runner(backtest_runner):
            self._runner = backtest_runner
        if self._is_valid_memory_dao(memory_vault_dao):
            self._memory_vault_dao = memory_vault_dao

    def _ensure_store(self):
        if not self._is_valid_store(self._store):
            self._store = StrategyStore()
        return self._store

    def _ensure_runner(self):
        if not self._is_valid_runner(self._runner):
            self._runner = BacktestRunner()
        return self._runner

    def _ensure_memory_vault_dao(self):
        if not self._is_valid_memory_dao(self._memory_vault_dao):
            self._memory_vault_dao = MemoryVaultDAO()
        return self._memory_vault_dao

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

    def list_strategy_history(self, *, limit: int = 50) -> list[dict[str, Any]]:
        versions = self.list_strategy_versions(limit=limit)
        type_map = {
            "BUILT_IN": "BASE",
            "MUTATION": "MUTATION",
            "CROSSOVER": "CROSSOVER",
            "BACKTEST": "FIX",
        }
        events: list[dict[str, Any]] = []
        for version in versions:
            origin = str(version.get("origin") or "BUILT_IN").strip().upper()
            status = str(version.get("status") or "draft").strip()
            metrics = version.get("metrics", {})
            normalized_metrics = metrics if isinstance(metrics, dict) else {}
            event_type = type_map.get(origin, "FIX")
            strategy_name = str(version.get("name") or "")
            event = {
                "id": str(version.get("id") or ""),
                "timestamp": version.get("created_at", 0),
                "type": event_type,
                "strategy_name": strategy_name,
                "message": (
                    f"v{self._to_int(version.get('version', 1), 1)} {origin.lower()} - "
                    f"status: {status or 'draft'}"
                ),
                "ooda": self._build_ooda_payload(
                    strategy_name=strategy_name,
                    event_type=event_type,
                    status=status or "draft",
                    metrics=normalized_metrics,
                ),
            }
            events.append(event)
        return events

    def search_knowledge(self, *, knowledge_type: str, query_text: str, top_k: int) -> Any:
        kb = self._create_knowledge_core()
        if knowledge_type == "pattern":
            return kb.search_patterns(query_text, top_k)
        if knowledge_type == "lesson":
            return kb.search_lessons(query_text, top_k)
        if knowledge_type == "rule":
            return kb.search_rules(query_text, top_k)
        return kb.search_all(query_text, top_k)

    def ingest_knowledge(
        self,
        *,
        knowledge_type: str,
        title: str,
        content: str,
        tags: list[str] | None = None,
        priority: int = 0,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        kb = self._create_knowledge_core()
        normalized_type = self._normalize_knowledge_type(knowledge_type)
        normalized_title = str(title or "").strip()
        normalized_content = str(content or "").strip()
        normalized_tags = self._normalize_knowledge_tags(tags)
        normalized_context = dict(context or {})

        if normalized_type == "pattern":
            entry_id = kb.add_pattern(
                name=normalized_title or "Pattern",
                description=normalized_content,
                context={**normalized_context, "tags": normalized_tags},
            )
        elif normalized_type == "lesson":
            entry_id = kb.add_lesson(
                title=normalized_title or "Lesson",
                content=normalized_content,
                tags=normalized_tags,
            )
        else:
            rule_text = normalized_content or normalized_title
            entry_id = kb.add_expert_rule(rule_text=rule_text, priority=int(priority))

        return {
            "id": str(entry_id),
            "entry_type": normalized_type,
            "title": normalized_title or normalized_content[:60] or "Knowledge",
            "content": normalized_content,
            "tags": normalized_tags,
            "priority": int(priority),
            "context": normalized_context,
        }

    def delete_knowledge(self, *, entry_id: str) -> bool:
        kb = self._create_knowledge_core()
        return bool(kb.delete_entry(str(entry_id or "").strip()))

    def get_memory_overrides(self) -> dict[str, Any]:
        dao = self._ensure_memory_vault_dao()
        payload = dao.get_overrides()
        tiers = payload.get("tiers", {}) if isinstance(payload.get("tiers", {}), dict) else {}
        forgotten = payload.get("forgotten", []) if isinstance(payload.get("forgotten", []), list) else []
        return {
            "tiers": {str(key): str(value).upper() for key, value in tiers.items() if str(key).strip()},
            "forgotten": [str(item) for item in forgotten if str(item).strip()],
            "updated_at": float(payload.get("updated_at", 0.0)),
        }

    def promote_memory(self, *, entry_id: str, current_tier: str) -> dict[str, Any]:
        normalized_id = str(entry_id or "").strip()
        if not normalized_id:
            raise ValueError("entry_id 不能为空")
        tier = self._normalize_memory_tier(current_tier)
        if tier == "COLD":
            next_tier = "WARM"
        elif tier == "WARM":
            next_tier = "HOT"
        else:
            next_tier = "HOT"
        dao = self._ensure_memory_vault_dao()
        payload = dao.set_tier(entry_id=normalized_id, tier=next_tier)
        return {"id": normalized_id, "tier": str(payload.get("tier") or next_tier)}

    def demote_memory(self, *, entry_id: str, current_tier: str) -> dict[str, Any]:
        normalized_id = str(entry_id or "").strip()
        if not normalized_id:
            raise ValueError("entry_id 不能为空")
        tier = self._normalize_memory_tier(current_tier)
        if tier == "HOT":
            next_tier = "WARM"
        elif tier == "WARM":
            next_tier = "COLD"
        else:
            next_tier = "COLD"
        dao = self._ensure_memory_vault_dao()
        payload = dao.set_tier(entry_id=normalized_id, tier=next_tier)
        return {"id": normalized_id, "tier": str(payload.get("tier") or next_tier)}

    def forget_memory(self, *, entry_id: str) -> dict[str, Any]:
        normalized_id = str(entry_id or "").strip()
        if not normalized_id:
            raise ValueError("entry_id 不能为空")
        dao = self._ensure_memory_vault_dao()
        payload = dao.forget(entry_id=normalized_id)
        return {"id": normalized_id, "forgotten": bool(payload.get("forgotten", True))}
