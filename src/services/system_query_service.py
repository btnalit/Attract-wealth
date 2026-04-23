"""Service layer for system query APIs backed by TradingLedger."""
from __future__ import annotations

from typing import Any

from src.core.trading_ledger import TradingLedger


class SystemQueryService:
    """Service layer for system query endpoints."""

    def get_llm_usage_summary(
        self,
        *,
        hours: int = 24,
        agent_id: str = "",
        session_id: str = "",
    ) -> dict[str, Any]:
        """Return aggregated LLM usage summary from ledger storage."""
        return TradingLedger.get_llm_usage_summary(hours=hours, agent_id=agent_id, session_id=session_id)

    def list_decision_evidence(
        self,
        *,
        limit: int = 50,
        ticker: str = "",
        session_id: str = "",
        phase: str = "",
        request_id: str = "",
        degraded_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Return decision evidence rows with filter constraints."""
        return TradingLedger.list_decision_evidence(
            limit=limit,
            ticker=ticker,
            session_id=session_id,
            phase=phase,
            request_id=request_id,
            degraded_only=degraded_only,
        )
