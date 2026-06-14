"""
Debate researcher: generate bullish and bearish arguments in parallel.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from src.core.agent_state import AgentState
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

        def _dump_payload(value: Any) -> Any:
            if hasattr(value, "model_dump"):
                return value.model_dump()
            if isinstance(value, dict):
                return dict(value)
            return value

        reports_text = json.dumps(
            {k: _dump_payload(v) for k, v in reports_dict.items()},
            ensure_ascii=False,
            indent=2,
        )

        bull_args, bear_args = await asyncio.gather(
            self._ask_bull(ticker, reports_text, session_id),
            self._ask_bear(ticker, reports_text, session_id),
        )
        sentiment_gap = self._compute_sentiment_gap(reports_dict, bull_args, bear_args)
        return DebateResult(
            bull_arguments=bull_args,
            bear_arguments=bear_args,
            sentiment_gap=sentiment_gap,
        )

    @staticmethod
    def _compute_sentiment_gap(
        reports_dict: dict[str, Any],
        bull_args: list[str],
        bear_args: list[str],
    ) -> float:
        """真实多空分歧度（0-100，越高分歧越大）。

        旧实现用 (bull+bear)*10，永远 60-100，无信息量。
        新实现综合：
        - 各 analyst score 的标准差（分数越分散分歧越大）
        - stance 多空数量接近度（bull≈bear 时分歧最大）
        """
        scores: list[float] = []
        bull = bear = neutral = 0
        for value in reports_dict.values():
            data = value.model_dump() if hasattr(value, "model_dump") else (
                dict(value) if isinstance(value, dict) else {}
            )
            try:
                scores.append(float(data.get("score", 50.0)))
            except (TypeError, ValueError):
                scores.append(50.0)
            stance = str(data.get("stance", "")).strip().lower()
            if stance == "bullish":
                bull += 1
            elif stance == "bearish":
                bear += 1
            else:
                neutral += 1

        # 因子1：score 标准差（0-50 区间，归一化到 0-100）
        import statistics
        if len(scores) >= 2:
            try:
                std = statistics.stdev(scores)
            except statistics.StatisticsError:
                std = 0.0
            score_spread = min(100.0, std * 4.0)  # std 25 → 100
        else:
            score_spread = 50.0  # 数据不足时中等分歧

        # 因子2：stance 分布分歧（bull≈bear 时最大）
        total = bull + bear + neutral
        if total > 0:
            # 多空平衡度：1 - |bull-bear|/total（完全平衡=1，单边=0）
            balance = 1.0 - abs(bull - bear) / total
            stance_gap = balance * 100.0
        else:
            stance_gap = 50.0

        # 综合分歧度：score 分布占 60%，stance 平衡度占 40%
        gap = score_spread * 0.6 + stance_gap * 0.4
        return round(min(100.0, max(0.0, gap)), 2)
