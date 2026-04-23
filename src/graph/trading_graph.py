"""
Attract-wealth trading graph composition based on LangGraph.
"""
from langgraph.graph import END, START, StateGraph

from src.agents.analysts.fundamental import FundamentalAnalyst
from src.agents.analysts.news import NewsAnalyst
from src.agents.analysts.technical import TechnicalAnalyst
from src.agents.researchers.debate import DebateResearcher
from src.agents.risk_mgmt.risk_manager import RiskManager
from src.agents.traders.trader import TraderAgent
from src.core.trading_vm import AgentState

fundamental_agent = FundamentalAnalyst()
technical_agent = TechnicalAnalyst()
news_agent = NewsAnalyst()
debate_researcher = DebateResearcher()
trader_agent = TraderAgent()
risk_manager = RiskManager()


async def _fundamental_node(state: AgentState) -> dict:
    report = await fundamental_agent.analyze(state)
    reports = state.get("analysis_reports", {})
    reports["fundamental"] = report
    return {"analysis_reports": reports}


async def _technical_node(state: AgentState) -> dict:
    report = await technical_agent.analyze(state)
    reports = state.get("analysis_reports", {})
    reports["technical"] = report
    return {"analysis_reports": reports}


async def _news_node(state: AgentState) -> dict:
    report = await news_agent.analyze(state)
    reports = state.get("analysis_reports", {})
    reports["news"] = report
    return {"analysis_reports": reports}


async def _debate_node(state: AgentState) -> dict:
    result = await debate_researcher.run_debate(state)
    if hasattr(result, "model_dump"):
        payload = result.model_dump()
    elif isinstance(result, dict):
        payload = dict(result)
    elif hasattr(result, "__dict__"):
        payload = dict(result.__dict__)
    else:
        payload = {"raw": str(result)}
    return {"debate_results": payload}


async def _trader_node(state: AgentState) -> dict:
    return await trader_agent.decide(state)


def _risk_node(state: AgentState) -> dict:
    return risk_manager.check_risk(state)


def build_trading_graph() -> StateGraph:
    builder = StateGraph(AgentState)

    builder.add_node("fundamental", _fundamental_node)
    builder.add_node("technical", _technical_node)
    builder.add_node("news", _news_node)
    builder.add_node("debate", _debate_node)
    builder.add_node("trader", _trader_node)
    builder.add_node("risk", _risk_node)

    builder.add_edge(START, "fundamental")
    builder.add_edge(START, "technical")
    builder.add_edge(START, "news")

    builder.add_edge("fundamental", "debate")
    builder.add_edge("technical", "debate")
    builder.add_edge("news", "debate")

    builder.add_edge("debate", "trader")
    builder.add_edge("trader", "risk")
    builder.add_edge("risk", END)

    return builder.compile()
