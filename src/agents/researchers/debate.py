"""
Debate researcher: generate bullish and bearish arguments in parallel.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from src.core.trading_vm import AgentState
from src.llm.openai_compat import create_deep_llm

logger = logging.getLogger(__name__)


class DebateResult(BaseModel):
    bull_arguments: list[str] = Field(default_factory=list)
    bear_arguments: list[str] = Field(default_factory=list)
    sentiment_gap: float = Field(default=0.0, description="0-100")


class DebateResearcher:
    """Run red/blue team market debate."""

    def __init__(self):
        self.llm = create_deep_llm()

    async def _ask_bull(self, ticker: str, reports_text: str, session_id: str) -> list[str]:
        prompt = (
            f"股票: {ticker}\n"
            f"分析上下文:\n{reports_text}\n\n"
            "请站在极度看多视角，给出 3-5 条最有力上涨逻辑。\n"
            '仅返回 JSON 数组，如 ["逻辑1","逻辑2"]。'
        )
        try:
            resp = await self.llm.chat_simple(
                prompt,
                system="你是激进多头分析师，只输出合法 JSON 数组。",
                session_id=session_id,
                agent_id="Debate_Bull_Agent",
            )
            clean = resp.replace("```json", "").replace("```", "").strip()
            parsed = json.loads(clean)
            return [str(item) for item in parsed] if isinstance(parsed, list) else ["Bull output invalid"]
        except Exception as exc:  # noqa: BLE001
            logger.error("Bull researcher failed: %s", exc)
            return [f"Bull generation failed: {exc}"]

    async def _ask_bear(self, ticker: str, reports_text: str, session_id: str) -> list[str]:
        prompt = (
            f"股票: {ticker}\n"
            f"分析上下文:\n{reports_text}\n\n"
            "请站在极度看空视角，给出 3-5 条最有力下跌逻辑。\n"
            '仅返回 JSON 数组，如 ["风险1","风险2"]。'
        )
        try:
            resp = await self.llm.chat_simple(
                prompt,
                system="你是审慎空头分析师，只输出合法 JSON 数组。",
                session_id=session_id,
                agent_id="Debate_Bear_Agent",
            )
            clean = resp.replace("```json", "").replace("```", "").strip()
            parsed = json.loads(clean)
            return [str(item) for item in parsed] if isinstance(parsed, list) else ["Bear output invalid"]
        except Exception as exc:  # noqa: BLE001
            logger.error("Bear researcher failed: %s", exc)
            return [f"Bear generation failed: {exc}"]

    async def run_debate(self, state: AgentState) -> DebateResult:
        ticker = state["ticker"]
        session_id = str(state.get("session_id", ""))
        reports_dict = state.get("analysis_reports", {})
        reports_text = json.dumps(
            {k: v.dict() if hasattr(v, "dict") else v for k, v in reports_dict.items()},
            ensure_ascii=False,
            indent=2,
        )

        bull_args, bear_args = await asyncio.gather(
            self._ask_bull(ticker, reports_text, session_id),
            self._ask_bear(ticker, reports_text, session_id),
        )
        sentiment_gap = min(100.0, max(0.0, float(len(bull_args) + len(bear_args)) * 10.0))
        return DebateResult(
            bull_arguments=bull_args,
            bear_arguments=bear_args,
            sentiment_gap=sentiment_gap,
        )
