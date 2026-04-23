"""
来财 (Attract-wealth) — TradingVM 核心执行引擎

TradingVM 将 LangGraph 状态图与 TradingLedger 结合，
负责处理用户的请求或定时任务的触发，并执行多 Agent 交易协同流程。
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, Optional, Protocol

from pydantic import BaseModel, Field

from src.core.agent_state import AgentState
from src.core.coordinator import AgentCoordinator
from src.core.cost_tracker import CostTracker
from src.core.hooks import HookManager
from src.core.permissions import PermissionGuard
from src.core.trading_ledger import TradingLedger, LedgerEntry
from src.core.tool_registry import ToolRegistry
from src.llm.openai_compat import get_llm_runtime_metrics


class _LLMRuntimeMetricsInput(BaseModel):
    """Input schema for runtime metrics governance tool."""

    session_id: str = Field(default="")
    ticker: str = Field(default="")


class _LLMUsageSummaryInput(BaseModel):
    """Input schema for usage summary governance tool."""

    hours: int = Field(default=24, ge=1, le=24 * 30)
    session_id: str = Field(default="")
    agent_id: str = Field(default="")


class RuntimeEventPublisher(Protocol):
    """Runtime event publisher contract for VM-side stream notifications."""

    def publish_log(self, agent_name: str, message: str, level: str = "info") -> None:
        ...

    def publish_node_transition(self, node_id: str, status: str, payload: dict | None = None) -> None:
        ...


class _NullRuntimeEventPublisher:
    """No-op publisher used when app composition does not inject stream events."""

    def publish_log(self, agent_name: str, message: str, level: str = "info") -> None:
        _ = (agent_name, message, level)

    def publish_node_transition(self, node_id: str, status: str, payload: dict | None = None) -> None:
        _ = (node_id, status, payload)


class TradingVM:
    """
    量化交易虚拟机
    - 初始化并编译 LangGraph 状态机
    - 提供执行网关
    - 记录执行日志和交易账本
    """

    def __init__(self, event_publisher: RuntimeEventPublisher | None = None):
        self.ledger = TradingLedger()
        self.permission_guard = PermissionGuard.from_env()
        self.hook_manager = HookManager()
        self.cost_tracker = CostTracker()
        self.event_publisher = event_publisher or _NullRuntimeEventPublisher()
        self.tool_registry = ToolRegistry(
            permission_guard=self.permission_guard,
            hook_manager=self.hook_manager,
        )
        self.coordinator = AgentCoordinator()
        self._register_default_governance_tools()
        self._graph_topology: dict[str, Any] = {}
        self.graph = self._build_graph()

    def _register_default_governance_tools(self) -> None:
        """Register built-in governance diagnostics tools."""

        def _llm_runtime_metrics(_payload: dict[str, Any]) -> dict[str, Any]:
            return get_llm_runtime_metrics()

        def _llm_usage_summary(payload: dict[str, Any]) -> dict[str, Any]:
            hours_raw = payload.get("hours", 24)
            session_id = str(payload.get("session_id", "") or "")
            agent_id = str(payload.get("agent_id", "") or "")
            try:
                hours = max(1, int(hours_raw))
            except (TypeError, ValueError):
                hours = 24
            return self.cost_tracker.get_usage_summary(hours=hours, session_id=session_id, agent_id=agent_id)

        self.tool_registry.register(
            name="llm_runtime_metrics",
            handler=_llm_runtime_metrics,
            description="Get LLM runtime governance metrics.",
            tags=["governance", "llm", "runtime"],
            input_model=_LLMRuntimeMetricsInput,
            example_payload={"session_id": "session_xxx", "ticker": "000001"},
        )
        self.tool_registry.register(
            name="llm_usage_summary",
            handler=_llm_usage_summary,
            description="Get ledger-based LLM usage summary.",
            tags=["governance", "llm", "cost"],
            input_model=_LLMUsageSummaryInput,
            example_payload={"hours": 24, "session_id": "session_xxx", "agent_id": "trader"},
        )

    def get_governance_snapshot(self) -> dict[str, Any]:
        """Expose core governance runtime snapshot."""
        permissions_snapshot = self.permission_guard.snapshot()
        hooks_snapshot = self.hook_manager.snapshot()
        tool_snapshot = self.tool_registry.snapshot()
        coordinator_snapshot = self.coordinator.snapshot()
        cost_snapshot = self.cost_tracker.runtime_snapshot()
        graph_snapshot = dict(self._graph_topology)
        tools = tool_snapshot.get("tools", [])
        tools_with_failures = [
            item.get("name", "")
            for item in tools
            if int((item.get("stats", {}) or {}).get("failed", 0)) > 0
        ]
        return {
            "permissions": permissions_snapshot,
            "hooks": hooks_snapshot,
            "tool_registry": tool_snapshot,
            "coordinator": coordinator_snapshot,
            "cost_tracker": cost_snapshot,
            "graph": graph_snapshot,
            "summary": {
                "permission_default_mode": permissions_snapshot.get("default_mode", "allow"),
                "registered_tools": len(tools),
                "tools_with_failures": tools_with_failures,
                "hook_errors_total": int(hooks_snapshot.get("errors_total", 0)),
                "coordinator_runs": int(coordinator_snapshot.get("runs", 0)),
                "graph_nodes": int(graph_snapshot.get("node_count", 0)),
                "graph_edges": int(graph_snapshot.get("edge_count", 0)),
            },
        }

    def _build_graph(self):
        """导入真实的 TradingGraph 编译并返回"""
        from src.graph.trading_graph import build_trading_graph, get_graph_topology

        self._graph_topology = get_graph_topology()
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
        await self.hook_manager.emit(
            "graph_start",
            {
                "session_id": session_id,
                "ticker": ticker,
            },
        )
        try:
            runtime_metrics = await self.tool_registry.execute(
                "llm_runtime_metrics",
                {"session_id": session_id, "ticker": ticker},
                actor="trading_vm",
            )
            if isinstance(runtime_metrics, dict):
                initial_state["context"]["llm_runtime"] = runtime_metrics
        except Exception:  # noqa: BLE001
            pass
        
        # 记录开始审计日志
        self.event_publisher.publish_node_transition("START", "active", {"ticker": ticker})
        self.event_publisher.publish_log("SYSTEM", f"Starting analysis for {ticker}")
        
        self.ledger.record_entry(LedgerEntry(
            category="SYSTEM",
            action="GRAPH_START",
            detail=f"Starting analysis for {ticker}",
            metadata={"session_id": session_id, "ticker": ticker}
        ))
        
        # 执行 LangGraph (带全局异常屏障 - QA 审计优化)
        try:
            final_state = await self.graph.ainvoke(initial_state)
            await self.hook_manager.emit(
                "graph_success",
                {
                    "session_id": session_id,
                    "ticker": ticker,
                    "decision": final_state.get("decision", "HOLD"),
                },
            )
            
            # 触发执行完成事件
            self.event_publisher.publish_node_transition(
                "END",
                "completed",
                {"decision": final_state.get("decision", "HOLD")},
            )
            self.event_publisher.publish_log("SYSTEM", f"Analysis complete: {final_state.get('decision', 'HOLD')}")
            final_state["governance"] = self.get_governance_snapshot()
            
            return final_state
            
        except Exception as e:
            error_msg = f"Graph execution failed: {str(e)}"
            await self.hook_manager.emit(
                "graph_error",
                {
                    "session_id": session_id,
                    "ticker": ticker,
                    "error": error_msg,
                },
            )
            self.event_publisher.publish_node_transition("ERROR", "error", {"error": error_msg})
            self.event_publisher.publish_log("SYSTEM", error_msg, level="error")
            
            self.ledger.record_entry(LedgerEntry(
                category="SYSTEM",
                action="GRAPH_ERROR",
                detail=error_msg,
                metadata={"session_id": session_id, "ticker": ticker, "traceback": str(e)}
            ))
            
            # 返回一个安全的状态，防止上层调用链崩溃
            initial_state["decision"] = "HOLD"
            initial_state["context"]["error"] = error_msg
            initial_state["governance"] = self.get_governance_snapshot()
            return initial_state

    async def run_batch(self, tickers: list[str], max_concurrency: int = 5) -> list[AgentState | None]:
        """
        批量、并发触发 Agent 分析任务（用于定时器自动寻天）
        """
        async def _worker(ticker: str) -> AgentState | None:
            try:
                return await self.run(ticker)
            except Exception as exc:  # noqa: BLE001
                self.ledger.record_entry(
                    LedgerEntry(
                        category="SYSTEM",
                        action="BATCH_ERROR",
                        detail=f"Error running {ticker}: {str(exc)}",
                        metadata={"ticker": ticker},
                    )
                )
                return None

        batch_results = await self.coordinator.run_batch(
            tickers,
            _worker,
            max_concurrency=max_concurrency,
        )
        return [item.get("result") for item in batch_results]
