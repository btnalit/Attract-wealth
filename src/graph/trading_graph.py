"""
来财 (Attract-wealth) — LangGraph 交易总流程网络

负责将数据收集、分析师组合、辩论组合、交易与风控编排为有向无环图 (DAG)。
"""
from typing import Any, Dict

from langgraph.graph import StateGraph, START, END

from src.core.trading_vm import AgentState
from src.agents.analysts.fundamental import FundamentalAnalyst
from src.agents.analysts.technical import TechnicalAnalyst
from src.agents.analysts.news import NewsAnalyst
from src.agents.researchers.debate import DebateResearcher
from src.agents.traders.trader import TraderAgent
from src.agents.risk_mgmt.risk_manager import RiskManager

# 实例化各组件
fundamental_agent = FundamentalAnalyst()
technical_agent = TechnicalAnalyst()
news_agent = NewsAnalyst()
debate_researcher = DebateResearcher()
trader_agent = TraderAgent()
risk_manager = RiskManager()


# ========== 节点包装函数 ==========

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
    # Pydantic 转 dict
    return {"debate_results": result.dict()}


async def _trader_node(state: AgentState) -> dict:
    return await trader_agent.decide(state)


def _risk_node(state: AgentState) -> dict:
    # 风控是同步硬规则的纯函数
    return risk_manager.check_risk(state)


# ========== 构建主图 ==========
def build_trading_graph() -> StateGraph:
    builder = StateGraph(AgentState)

    # 1. 注册平行并连的分析师节点
    builder.add_node("fundamental", _fundamental_node)
    builder.add_node("technical", _technical_node)
    builder.add_node("news", _news_node)

    # 2. 辩论节点
    builder.add_node("debate", _debate_node)

    # 3. 交易拍板节点
    builder.add_node("trader", _trader_node)

    # 4. 风控兜底节点
    builder.add_node("risk", _risk_node)

    # ---- 绘制 Edge 连接 ----
    # 启动时：同时并发唤醒三名分析师
    builder.add_edge(START, "fundamental")
    builder.add_edge(START, "technical")
    builder.add_edge(START, "news")

    # 分析完成后：汇聚到圆桌辩论节点
    builder.add_edge("fundamental", "debate")
    builder.add_edge("technical", "debate")
    builder.add_edge("news", "debate")

    # 辩论完成后：交给首席交易大脑
    builder.add_edge("debate", "trader")

    # 交易完成：接受风控合规审查
    builder.add_edge("trader", "risk")

    # 合规检查后直接结束流程
    builder.add_edge("risk", END)

    # 返回 compile() 之后的可运行实体
    return builder.compile()
