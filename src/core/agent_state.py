"""
Shared agent state contract used across graph/agents/vm.
"""
from __future__ import annotations

from typing import Annotated, Any

from typing_extensions import NotRequired, TypedDict


def merge_reports(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    """Reducer for analysis_reports：并行 analyst 各自写入自己的报告，需合并而非覆盖。

    P2-2：analyst 并行化后，fundamental/technical/news 三个节点会并发返回
    {"analysis_reports": {自己的key: 自己的report}}，必须用合并 reducer 才能保留全部。
    """
    if left is None and right is None:
        return {}
    if left is None:
        return dict(right or {})
    if right is None:
        return dict(left)
    merged = dict(left)
    merged.update(right)
    return merged


class AgentState(TypedDict):
    """Canonical runtime state passed through the trading graph."""

    session_id: str
    ticker: str
    messages: list[Any]
    current_agent: str
    decision: str  # BUY / SELL / HOLD
    confidence: float
    # P2-2：合并 reducer —— 并行 analyst 节点各自写自己的 key，最终合并为完整 dict
    analysis_reports: Annotated[dict[str, Any], merge_reports]
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
