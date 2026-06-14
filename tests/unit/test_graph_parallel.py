# -*- coding: utf-8 -*-
"""P2-2：analyst 并行化测试。

验证：
1. 拓扑：三个 analyst 从 START fan-out，再 fan-in 到 signal_processing
2. 语义：所有三个 analyst 报告都正确合并到 analysis_reports（不互相覆盖）
3. 性能：并行执行时间 < 串行执行时间之和
"""
from __future__ import annotations

import asyncio
import time

import pytest

from src.core.agent_state import merge_reports
from src.graph.trading_graph import (
    GRAPH_EDGE_SEQUENCE,
    PARALLEL_ANALYSTS,
    TradingGraphAgents,
    build_trading_graph,
    get_graph_topology,
)


# ===== merge_reports reducer =====
class TestMergeReportsReducer:
    def test_both_none_returns_empty(self):
        assert merge_reports(None, None) == {}

    def test_left_none_returns_right_copy(self):
        right = {"a": 1}
        result = merge_reports(None, right)
        assert result == {"a": 1}
        assert result is not right  # 是拷贝，不是引用

    def test_right_none_returns_left_copy(self):
        left = {"a": 1}
        result = merge_reports(left, None)
        assert result == {"a": 1}
        assert result is not left

    def test_both_merge_with_right_precedence(self):
        left = {"a": 1, "b": 2}
        right = {"b": 99, "c": 3}
        result = merge_reports(left, right)
        assert result == {"a": 1, "b": 99, "c": 3}  # right 的 b 覆盖 left 的 b


# ===== 拓扑：fan-out/fan-in =====
class TestParallelTopology:
    def test_start_fans_out_to_all_analysts(self):
        """START 应有边到每个 analyst。"""
        start_targets = {to for frm, to in GRAPH_EDGE_SEQUENCE if frm == "START"}
        assert set(PARALLEL_ANALYSTS).issubset(start_targets)

    def test_all_analysts_fan_in_to_signal_processing(self):
        """每个 analyst 都应有边到 signal_processing。"""
        analyst_sources = {
            frm for frm, to in GRAPH_EDGE_SEQUENCE if to == "signal_processing"
        }
        assert set(PARALLEL_ANALYSTS) == analyst_sources

    def test_no_serial_edges_between_analysts(self):
        """不应再有 fundamental→technical→news 的串行边。"""
        for a, b in GRAPH_EDGE_SEQUENCE:
            if a in PARALLEL_ANALYSTS and b in PARALLEL_ANALYSTS:
                pytest.fail(f"存在串行边 {a}→{b}，应已并行化")

    def test_topology_has_parallel_groups(self):
        topo = get_graph_topology()
        assert "parallel_groups" in topo
        assert list(PARALLEL_ANALYSTS) in topo["parallel_groups"]
        assert topo["entrypoint_count"] == len(PARALLEL_ANALYSTS)


# ===== 语义：三个 analyst 报告都保留 =====
class _SleepAnalyst:
    """模拟 analyst：睡 sleep_s 秒后返回报告（用于验证并行加速）。

    analyst_type 故意与节点名不同（模拟 NewsAnalyst.analyst_name="Sentiment_Agent"），
    用于回归断言：节点写入的 dict key 必须是节点名（fundamental/technical/news），
    而非 analyst_type 派生的值。
    """

    def __init__(self, *, name: str, analyst_type: str, sleep_s: float) -> None:
        self.name = name
        self.analyst_type = analyst_type
        self.sleep_s = sleep_s

    async def analyze(self, state: dict) -> dict:
        await asyncio.sleep(self.sleep_s)
        return {
            "analyst_type": self.analyst_type,
            "ticker": state.get("ticker", ""),
            "score": 60.0,
            "stance": "Bullish",
            "summary": f"{self.name}-ok",
            "key_factors": [f"{self.name}-factor"],
        }


class _FakeDebate:
    async def run_debate(self, _state: dict) -> dict:
        return {"bull_arguments": ["b"], "bear_arguments": ["r"], "sentiment_gap": 40.0}


class _FakeTrader:
    async def decide(self, state: dict) -> dict:
        return {"decision": "BUY", "confidence": 80.0,
                "trading_decision": {"action": "BUY", "percentage": 10.0, "reason": "ok", "confidence": 80.0}}


class _FakeRisk:
    def check_risk(self, state: dict) -> dict:
        return {"risk_check": {"passed": True, "reason": "ok"}}


def _real_analyst_names() -> tuple[tuple[str, str], tuple[str, str], tuple[str, str]]:
    """返回 (节点名, analyst_type) 三元组，用真实生产 analyst_name 捕捉 key 稳定性回归。"""
    return (
        ("fundamental", "Fundamental_Agent"),
        ("technical", "Technical_Agent"),
        ("news", "Sentiment_Agent"),  # 关键：NewsAnalyst.analyst_name 是 Sentiment_Agent
    )


class TestParallelSemanticsAndPerformance:
    def test_all_three_reports_preserved_with_real_analyst_names(self):
        """并行执行后三个 analyst 的报告都应保留在 analysis_reports。

        用真实 analyst_name（含 Sentiment_Agent）回归断言：dict key 必须是
        节点名 {fundamental, technical, news}，不能被 analyst_type 派生为 sentiment。
        """
        (fn, ft), (tn, tt), (nn, nt) = _real_analyst_names()
        agents = TradingGraphAgents(
            fundamental=_SleepAnalyst(name=fn, analyst_type=ft, sleep_s=0.01),
            technical=_SleepAnalyst(name=tn, analyst_type=tt, sleep_s=0.01),
            news=_SleepAnalyst(name=nn, analyst_type=nt, sleep_s=0.01),
            debate=_FakeDebate(),
            trader=_FakeTrader(),
            risk=_FakeRisk(),
        )
        graph = build_trading_graph(agents=agents)
        state = {
            "session_id": "s1", "ticker": "000001", "messages": [],
            "current_agent": "system", "decision": "HOLD", "confidence": 0.0,
            "analysis_reports": {}, "context": {},
        }
        result = asyncio.run(graph.ainvoke(state))
        # 关键断言：key 是节点名，不是 analyst_type 派生值
        assert set(result["analysis_reports"].keys()) == {"fundamental", "technical", "news"}
        # analyst_type 字段内容仍保留原值（Sentiment_Agent）
        assert result["analysis_reports"]["news"]["analyst_type"] == "Sentiment_Agent"

    def test_parallel_is_faster_than_serial_sum(self):
        """并行执行时间应明显小于三个 analyst 睡眠时间之和。

        每个 analyst 睡 0.2s，串行需 ~0.6s，并行应 ~0.2s。
        容差设为 0.45s（留出调度开销，但仍远小于 0.6s）。
        """
        per_analyst_sleep = 0.2
        agents = TradingGraphAgents(
            fundamental=_SleepAnalyst(name="fundamental", analyst_type="Fundamental_Agent", sleep_s=per_analyst_sleep),
            technical=_SleepAnalyst(name="technical", analyst_type="Technical_Agent", sleep_s=per_analyst_sleep),
            news=_SleepAnalyst(name="news", analyst_type="Sentiment_Agent", sleep_s=per_analyst_sleep),
            debate=_FakeDebate(),
            trader=_FakeTrader(),
            risk=_FakeRisk(),
        )
        graph = build_trading_graph(agents=agents)
        state = {
            "session_id": "s2", "ticker": "000001", "messages": [],
            "current_agent": "system", "decision": "HOLD", "confidence": 0.0,
            "analysis_reports": {}, "context": {},
        }

        start = time.monotonic()
        asyncio.run(graph.ainvoke(state))
        elapsed = time.monotonic() - start

        serial_total = per_analyst_sleep * len(PARALLEL_ANALYSTS)  # 0.6s
        # 并行应远快于串行总和（留调度开销余量）
        assert elapsed < serial_total * 0.75, (
            f"并行耗时 {elapsed:.3f}s 未明显优于串行 {serial_total:.3f}s"
        )


# ===== 节点级容错：单个 analyst 异常不中断整图 =====
class _BoomAnalyst:
    """总是抛异常的 analyst（模拟 LLM 超时/取数失败）。"""

    def __init__(self, *, analyst_type: str) -> None:
        self.analyst_type = analyst_type

    async def analyze(self, state: dict) -> dict:
        raise RuntimeError(f"{self.analyst_type} crashed")


class TestAnalystFaultTolerance:
    def test_one_analyst_crash_does_not_break_graph(self):
        """单个 analyst 抛异常时，graph 应降级而非崩溃，其它两个报告仍保留。"""
        agents = TradingGraphAgents(
            fundamental=_SleepAnalyst(name="fundamental", analyst_type="Fundamental_Agent", sleep_s=0.01),
            technical=_BoomAnalyst(analyst_type="Technical_Agent"),  # 崩溃
            news=_SleepAnalyst(name="news", analyst_type="Sentiment_Agent", sleep_s=0.01),
            debate=_FakeDebate(),
            trader=_FakeTrader(),
            risk=_FakeRisk(),
        )
        graph = build_trading_graph(agents=agents)
        state = {
            "session_id": "s1", "ticker": "000001", "messages": [],
            "current_agent": "system", "decision": "HOLD", "confidence": 0.0,
            "analysis_reports": {}, "context": {},
        }
        # 不应抛异常
        result = asyncio.run(graph.ainvoke(state))
        # 三个 key 都在（technical 是降级的中性报告）
        assert set(result["analysis_reports"].keys()) == {"fundamental", "technical", "news"}
        # technical 降级为中性
        tech = result["analysis_reports"]["technical"]
        assert tech["score"] == 50.0
        assert tech["stance"] == "Neutral"
        assert "degraded" in tech["summary"].lower() or "异常" in tech["summary"]

    def test_all_analysts_crash_still_produces_reports(self):
        """所有 analyst 都崩溃时，graph 仍应产出三份降级报告（不空）。"""
        agents = TradingGraphAgents(
            fundamental=_BoomAnalyst(analyst_type="Fundamental_Agent"),
            technical=_BoomAnalyst(analyst_type="Technical_Agent"),
            news=_BoomAnalyst(analyst_type="Sentiment_Agent"),
            debate=_FakeDebate(),
            trader=_FakeTrader(),
            risk=_FakeRisk(),
        )
        graph = build_trading_graph(agents=agents)
        state = {
            "session_id": "s2", "ticker": "000002", "messages": [],
            "current_agent": "system", "decision": "HOLD", "confidence": 0.0,
            "analysis_reports": {}, "context": {},
        }
        result = asyncio.run(graph.ainvoke(state))
        assert len(result["analysis_reports"]) == 3
        # 全部降级为中性
        for r in result["analysis_reports"].values():
            assert r["score"] == 50.0
