"""
Conditional helpers for graph node branching decisions.
"""
from __future__ import annotations

from src.core.agent_state import AgentState


def should_run_debate(state: AgentState) -> bool:
    """Return whether debate stage has enough upstream signals to run."""
    reports = state.get("analysis_reports", {})
    if not isinstance(reports, dict) or not reports:
        return False

    for value in reports.values():
        if isinstance(value, dict):
            summary = str(value.get("summary", "")).strip()
            if summary:
                return True
        elif hasattr(value, "summary") and str(getattr(value, "summary", "")).strip():
            return True
    return False


def build_debate_skip_payload(state: AgentState) -> dict[str, object]:
    """Fallback payload when debate stage is skipped."""
    return {
        "bull_arguments": [],
        "bear_arguments": [],
        "sentiment_gap": 0.0,
        "skipped": True,
        "reason": "insufficient_signal_context",
        "ticker": str(state.get("ticker", "")),
    }


def summarize_risk_status(state: AgentState) -> str:
    """Return normalized risk status label for reflection layer."""
    risk_check = state.get("risk_check", {})
    if not isinstance(risk_check, dict):
        return "unknown"
    if risk_check.get("passed") is True:
        return "passed"
    if risk_check.get("passed") is False:
        return "rejected"
    return "unknown"
