from __future__ import annotations

import asyncio

from src.graph.trading_graph import TradingGraphAgents, build_trading_graph, get_graph_topology


class _FakeAnalyst:
    def __init__(self, *, name: str, summary: str, score: float, stance: str = "Neutral") -> None:
        self.name = name
        self.summary = summary
        self.score = score
        self.stance = stance

    async def analyze(self, state: dict) -> dict:
        return {
            "analyst_type": self.name,
            "ticker": state.get("ticker", ""),
            "score": self.score,
            "stance": self.stance,
            "summary": self.summary,
            "key_factors": [f"{self.name}-factor"],
        }


class _FakeDebate:
    async def run_debate(self, _state: dict) -> dict:
        return {
            "bull_arguments": ["bull-1"],
            "bear_arguments": ["bear-1"],
            "sentiment_gap": 40.0,
        }


class _FakeTrader:
    async def decide(self, state: dict) -> dict:
        debate = state.get("debate_results", {})
        skipped = bool((debate or {}).get("skipped"))
        action = "HOLD" if skipped else "BUY"
        confidence = 35.0 if skipped else 82.0
        return {
            "decision": action,
            "confidence": confidence,
            "trading_decision": {
                "action": action,
                "percentage": 0.0 if skipped else 10.0,
                "reason": "debate skipped" if skipped else "signals aligned",
                "confidence": confidence,
            },
        }


class _FakeRisk:
    def check_risk(self, state: dict) -> dict:
        action = str((state.get("trading_decision", {}) or {}).get("action", "HOLD"))
        if action == "BUY":
            return {"risk_check": {"passed": True, "reason": "ok"}}
        return {"risk_check": {"passed": True, "reason": "no action"}}


def _run(coro):
    return asyncio.run(coro)


def test_graph_pipeline_with_injected_agents_runs_end_to_end():
    agents = TradingGraphAgents(
        fundamental=_FakeAnalyst(name="fundamental", summary="f-ok", score=70.0, stance="Bullish"),
        technical=_FakeAnalyst(name="technical", summary="t-ok", score=60.0, stance="Bullish"),
        news=_FakeAnalyst(name="news", summary="n-ok", score=55.0, stance="Neutral"),
        debate=_FakeDebate(),
        trader=_FakeTrader(),
        risk=_FakeRisk(),
    )
    graph = build_trading_graph(agents=agents)

    state = {
        "session_id": "s1",
        "ticker": "000001",
        "messages": [],
        "current_agent": "system",
        "decision": "HOLD",
        "confidence": 0.0,
        "analysis_reports": {},
        "context": {},
    }
    result = _run(graph.ainvoke(state))
    assert result["decision"] == "BUY"
    assert result["risk_check"]["passed"] is True
    assert set(result["analysis_reports"].keys()) == {"fundamental", "technical", "news"}
    assert result["context"]["signal_summary"]["report_count"] == 3
    assert result["context"]["graph_reflection"]["risk_status"] == "passed"


def test_graph_pipeline_skips_debate_when_signals_missing():
    agents = TradingGraphAgents(
        fundamental=_FakeAnalyst(name="fundamental", summary="", score=50.0),
        technical=_FakeAnalyst(name="technical", summary="", score=50.0),
        news=_FakeAnalyst(name="news", summary="", score=50.0),
        debate=_FakeDebate(),
        trader=_FakeTrader(),
        risk=_FakeRisk(),
    )
    graph = build_trading_graph(agents=agents)
    state = {
        "session_id": "s2",
        "ticker": "000002",
        "messages": [],
        "current_agent": "system",
        "decision": "HOLD",
        "confidence": 0.0,
        "analysis_reports": {},
        "context": {},
    }
    result = _run(graph.ainvoke(state))
    assert result["debate_results"]["skipped"] is True
    assert result["decision"] == "HOLD"
    assert result["trading_decision"]["reason"] == "debate skipped"


def test_graph_topology_metadata_contains_split_modules():
    topology = get_graph_topology()
    assert "signal_processing" in topology["nodes"]
    assert "reflection" in topology["nodes"]
    assert topology["node_count"] == len(topology["nodes"])
    assert topology["edge_count"] == len(topology["edges"])
