"""
Shared agent state contract used across graph/agents/vm.
"""
from __future__ import annotations

from typing import Any

from typing_extensions import NotRequired, TypedDict


class AgentState(TypedDict):
    """Canonical runtime state passed through the trading graph."""

    session_id: str
    ticker: str
    messages: list[Any]
    current_agent: str
    decision: str  # BUY / SELL / HOLD
    confidence: float
    analysis_reports: dict[str, Any]
    context: dict[str, Any]
    debate_results: NotRequired[dict[str, Any]]
    trading_decision: NotRequired[dict[str, Any]]
    risk_check: NotRequired[dict[str, Any]]
    degrade_flags: NotRequired[list[str]]
    degrade_warnings: NotRequired[list[str]]
    degrade_policy: NotRequired[dict[str, Any]]
    trace_id: NotRequired[str]
    request_id: NotRequired[str]
    trace: NotRequired[dict[str, Any]]
