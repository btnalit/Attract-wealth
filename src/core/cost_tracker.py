"""Unified cost governance facade backed by TradingLedger."""
from __future__ import annotations

import os
from typing import Any

from src.core.trading_ledger import TradingLedger


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


class CostTracker:
    """Cost tracker for LLM usage summary and budget checks."""

    def get_usage_summary(self, *, hours: int = 24, session_id: str = "", agent_id: str = "") -> dict[str, Any]:
        return TradingLedger.get_llm_usage_summary(hours=hours, session_id=session_id, agent_id=agent_id)

    def record_usage(self, payload: dict[str, Any]) -> None:
        TradingLedger.record_llm_usage(payload)

    def daily_budget_status(
        self,
        *,
        daily_budget_usd: float,
        current_call_cost: float = 0.0,
        hours: int = 24,
        session_id: str = "",
        agent_id: str = "",
    ) -> dict[str, Any]:
        summary = self.get_usage_summary(hours=hours, session_id=session_id, agent_id=agent_id)
        current_cost = _to_float(summary.get("cost_usd", 0.0))
        projected_cost = current_cost + max(0.0, _to_float(current_call_cost, 0.0))
        budget = max(0.0, _to_float(daily_budget_usd, 0.0))
        exceeded = bool(budget > 0 and projected_cost > budget)
        return {
            "budget_usd": budget,
            "current_cost_usd": round(current_cost, 6),
            "current_call_cost_usd": round(max(0.0, _to_float(current_call_cost, 0.0)), 6),
            "projected_cost_usd": round(projected_cost, 6),
            "exceeded": exceeded,
            "remaining_usd": round(max(0.0, budget - projected_cost), 6) if budget > 0 else 0.0,
            "summary": summary,
        }

    def runtime_snapshot(self) -> dict[str, Any]:
        budget = _to_float(os.getenv("LLM_DAILY_BUDGET_USD", "0"), 0.0)
        budget_status = self.daily_budget_status(daily_budget_usd=budget)
        return {
            "usage_24h": budget_status.get("summary", {}),
            "budget": {
                "daily_budget_usd": budget_status.get("budget_usd", 0.0),
                "current_cost_usd": budget_status.get("current_cost_usd", 0.0),
                "projected_cost_usd": budget_status.get("projected_cost_usd", 0.0),
                "remaining_usd": budget_status.get("remaining_usd", 0.0),
                "exceeded": budget_status.get("exceeded", False),
            },
        }
