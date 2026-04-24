"""
Attract-wealth trading graph composition based on LangGraph.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langgraph.graph import END, START, StateGraph

from src.agents.analysts.fundamental import FundamentalAnalyst
from src.agents.analysts.news import NewsAnalyst
from src.agents.analysts.technical import TechnicalAnalyst
from src.agents.researchers.debate import DebateResearcher
from src.agents.risk_mgmt.risk_manager import RiskManager
from src.agents.traders.trader import TraderAgent
from src.core.agent_state import AgentState
from src.graph.conditional_logic import build_debate_skip_payload, should_run_debate
from src.graph.reflection import build_reflection_patch
from src.graph.signal_processing import (
    build_signal_context_patch,
    merge_analysis_report,
    normalize_debate_result,
)


GRAPH_NODE_SEQUENCE: tuple[str, ...] = (
    "fundamental",
    "technical",
    "news",
    "signal_processing",
    "debate",
    "trader",
    "risk",
    "reflection",
)
GRAPH_EDGE_SEQUENCE: tuple[tuple[str, str], ...] = (
    ("START", "fundamental"),
    ("fundamental", "technical"),
    ("technical", "news"),
    ("news", "signal_processing"),
    ("signal_processing", "debate"),
    ("debate", "trader"),
    ("trader", "risk"),
    ("risk", "reflection"),
    ("reflection", "END"),
)


@dataclass
class TradingGraphAgents:
    """Agent bundle used by graph nodes."""

    fundamental: Any
    technical: Any
    news: Any
    debate: Any
    trader: Any
    risk: Any


def build_default_agents() -> TradingGraphAgents:
    """Create default production agent bundle."""
    return TradingGraphAgents(
        fundamental=FundamentalAnalyst(),
        technical=TechnicalAnalyst(),
        news=NewsAnalyst(),
        debate=DebateResearcher(),
        trader=TraderAgent(),
        risk=RiskManager(),
    )


def get_graph_topology() -> dict[str, Any]:
    """Return graph topology metadata for runtime governance snapshot."""
    return {
        "nodes": list(GRAPH_NODE_SEQUENCE),
        "edges": [{"from": source, "to": target} for source, target in GRAPH_EDGE_SEQUENCE],
        "node_count": len(GRAPH_NODE_SEQUENCE),
        "edge_count": len(GRAPH_EDGE_SEQUENCE),
        "entrypoint_count": 1,
    }


def build_trading_graph(*, agents: TradingGraphAgents | None = None):
    """Build and compile trading graph with injectable agent dependencies."""
    graph_agents = agents or build_default_agents()
    builder = StateGraph(AgentState)

    async def _fundamental_node(state: AgentState) -> dict[str, Any]:
        report = await graph_agents.fundamental.analyze(state)
        return {
            "analysis_reports": merge_analysis_report(state, report_type="fundamental", report=report),
        }

    async def _technical_node(state: AgentState) -> dict[str, Any]:
        report = await graph_agents.technical.analyze(state)
        return {
            "analysis_reports": merge_analysis_report(state, report_type="technical", report=report),
        }

    async def _news_node(state: AgentState) -> dict[str, Any]:
        report = await graph_agents.news.analyze(state)
        return {
            "analysis_reports": merge_analysis_report(state, report_type="news", report=report),
        }

    def _signal_processing_node(state: AgentState) -> dict[str, Any]:
        return build_signal_context_patch(state)

    async def _debate_node(state: AgentState) -> dict[str, Any]:
        if not should_run_debate(state):
            return {"debate_results": build_debate_skip_payload(state)}
        result = await graph_agents.debate.run_debate(state)
        return {"debate_results": normalize_debate_result(result)}

    async def _trader_node(state: AgentState) -> dict[str, Any]:
        return await graph_agents.trader.decide(state)

    def _risk_node(state: AgentState) -> dict[str, Any]:
        return graph_agents.risk.check_risk(state)

    def _reflection_node(state: AgentState) -> dict[str, Any]:
        return build_reflection_patch(state)

    builder.add_node("fundamental", _fundamental_node)
    builder.add_node("technical", _technical_node)
    builder.add_node("news", _news_node)
    builder.add_node("signal_processing", _signal_processing_node)
    builder.add_node("debate", _debate_node)
    builder.add_node("trader", _trader_node)
    builder.add_node("risk", _risk_node)
    builder.add_node("reflection", _reflection_node)

    builder.add_edge(START, "fundamental")
    builder.add_edge("fundamental", "technical")
    builder.add_edge("technical", "news")
    builder.add_edge("news", "signal_processing")

    builder.add_edge("signal_processing", "debate")
    builder.add_edge("debate", "trader")
    builder.add_edge("trader", "risk")
    builder.add_edge("risk", "reflection")
    builder.add_edge("reflection", END)

    return builder.compile()
