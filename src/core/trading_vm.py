"""
来财 (Attract-wealth) — TradingVM 核心执行引擎

TradingVM 将 LangGraph 状态图与 TradingLedger 结合，
负责处理用户的请求或定时任务的触发，并执行多 Agent 交易协同流程。
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from langgraph.graph import StateGraph, START, END
from typing_extensions import NotRequired, TypedDict

from src.core.trading_ledger import TradingLedger, LedgerEntry


# 定义全局的 Trading Graph 状态
class AgentState(TypedDict):
    session_id: str
    ticker: str
    messages: list[Any]
    current_agent: str
    decision: str  # BUY / SELL / HOLD
    confidence: float
    analysis_reports: dict[str, str]
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


class TradingVM:
    """
    量化交易虚拟机
    - 初始化并编译 LangGraph 状态机
    - 提供执行网关
    - 记录执行日志和交易账本
    """

    def __init__(self):
        self.ledger = TradingLedger()
        self.graph = self._build_graph()

    def _build_graph(self):
        """导入真实的 TradingGraph 编译并返回"""
        from src.graph.trading_graph import build_trading_graph
        return build_trading_graph()

    async def run(self, ticker: str, initial_context: Optional[Dict[str, Any]] = None) -> AgentState:
        """
        触发图执行
        """
        session_id = f"session_{uuid.uuid4().hex[:8]}"
        initial_state = {
            "session_id": session_id,
            "ticker": ticker,
            "messages": [],
            "current_agent": "system",
            "decision": "HOLD",
            "confidence": 0.0,
            "analysis_reports": {},
            "context": initial_context or {},
        }
        
        # 记录开始审计日志
        from src.routers.stream import publish_node_transition, publish_log
        
        publish_node_transition("START", "active", {"ticker": ticker})
        publish_log("SYSTEM", f"Starting analysis for {ticker}")
        
        self.ledger.record_entry(LedgerEntry(
            category="SYSTEM",
            action="GRAPH_START",
            detail=f"Starting analysis for {ticker}",
            metadata={"session_id": session_id, "ticker": ticker}
        ))
        
        # 执行 LangGraph (带全局异常屏障 - QA 审计优化)
        try:
            final_state = await self.graph.ainvoke(initial_state)
            
            # 触发执行完成事件
            publish_node_transition("END", "completed", {"decision": final_state.get('decision', 'HOLD')})
            publish_log("SYSTEM", f"Analysis complete: {final_state.get('decision', 'HOLD')}")
            
            return final_state
            
        except Exception as e:
            error_msg = f"Graph execution failed: {str(e)}"
            publish_node_transition("ERROR", "error", {"error": error_msg})
            publish_log("SYSTEM", error_msg, level="error")
            
            self.ledger.record_entry(LedgerEntry(
                category="SYSTEM",
                action="GRAPH_ERROR",
                detail=error_msg,
                metadata={"session_id": session_id, "ticker": ticker, "traceback": str(e)}
            ))
            
            # 返回一个安全的状态，防止上层调用链崩溃
            initial_state["decision"] = "HOLD"
            initial_state["context"]["error"] = error_msg
            return initial_state

    async def run_batch(self, tickers: list[str], max_concurrency: int = 5) -> list[AgentState]:
        """
        批量、并发触发 Agent 分析任务（用于定时器自动寻天）
        """
        import asyncio
        semaphore = asyncio.Semaphore(max_concurrency)
        
        async def _run_with_sem(ticker):
            async with semaphore:
                try:
                    return await self.run(ticker)
                except Exception as e:
                    self.ledger.record_entry(LedgerEntry(
                        category="SYSTEM",
                        action="BATCH_ERROR",
                        detail=f"Error running {ticker}: {str(e)}",
                        metadata={"ticker": ticker}
                    ))
                    return None

        tasks = [_run_with_sem(t) for t in tickers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return results
