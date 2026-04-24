"""
Graph reflection helpers.
"""
from __future__ import annotations

import time
from typing import Any

from src.core.agent_state import AgentState
from src.graph.conditional_logic import summarize_risk_status


def build_reflection_patch(state: AgentState) -> dict[str, Any]:
    """Create post-risk reflection snapshot for runtime audit."""
    context = state.get("context", {})
    merged_context = dict(context if isinstance(context, dict) else {})
    merged_context["graph_reflection"] = {
        "at_ts": time.time(),
        "ticker": str(state.get("ticker", "")),
        "decision": str(state.get("decision", "HOLD")),
        "confidence": float(state.get("confidence", 0.0) or 0.0),
        "risk_status": summarize_risk_status(state),
        "degrade_flags": list(state.get("degrade_flags", [])) if isinstance(state.get("degrade_flags", []), list) else [],
        "analysis_report_count": len(state.get("analysis_reports", {})) if isinstance(state.get("analysis_reports", {}), dict) else 0,
    }
    return {"context": merged_context}
