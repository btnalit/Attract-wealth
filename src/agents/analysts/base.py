"""
Base building blocks for analyst agents.
"""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field

from src.core.trading_vm import AgentState
from src.llm.openai_compat import create_quick_llm

logger = logging.getLogger(__name__)


class AnalystReport(BaseModel):
    """Normalized analyst output used by the graph."""

    analyst_type: str
    ticker: str
    score: float = Field(default=50.0, description="0-100")
    stance: str = Field(default="Neutral", description="Bullish/Bearish/Neutral")
    summary: str = Field(default="", description="Short explanation")
    key_factors: list[str] = Field(default_factory=list, description="Main drivers")


class BaseAnalyst(ABC):
    """Base behavior for all analysts."""

    analyst_name = "BaseAnalyst"

    def __init__(self):
        self.llm = create_quick_llm()

    @abstractmethod
    async def analyze(self, state: AgentState) -> AnalystReport:
        ...

    async def _ask_llm_for_report(
        self,
        ticker: str,
        context: str,
        system_prompt: str,
        *,
        session_id: str = "",
    ) -> AnalystReport:
        prompt = (
            f"股票: {ticker}\n"
            "上下文数据:\n"
            f"{context}\n\n"
            "请仅输出 JSON 对象，不要包含 markdown 代码块。\n"
            "JSON 格式:\n"
            "{\n"
            f'  "analyst_type": "{self.analyst_name}",\n'
            f'  "ticker": "{ticker}",\n'
            '  "score": 0,\n'
            '  "stance": "Bullish",\n'
            '  "summary": "简要结论",\n'
            '  "key_factors": ["因素1", "因素2"]\n'
            "}"
        )

        try:
            text = await self.llm.chat_simple(
                prompt,
                system=system_prompt,
                session_id=session_id,
                agent_id=self.analyst_name,
            )
            data = self._parse_json_payload(text)
            normalized = self._normalize_payload(ticker=ticker, payload=data)
            return AnalystReport(**normalized)
        except Exception as exc:  # noqa: BLE001
            logger.error("[%s] report parsing failed: %s", self.analyst_name, exc)
            return AnalystReport(
                analyst_type=self.analyst_name,
                ticker=ticker,
                score=50.0,
                stance="Neutral",
                summary=f"LLM fallback: {exc}",
                key_factors=["LLM Failure"],
            )

    def _parse_json_payload(self, text: str) -> dict[str, Any]:
        clean = (text or "").replace("```json", "").replace("```", "").strip()
        payload = json.loads(clean)
        if not isinstance(payload, dict):
            raise ValueError(f"expected JSON object, got: {type(payload).__name__}")
        return payload

    def _normalize_payload(self, *, ticker: str, payload: dict[str, Any]) -> dict[str, Any]:
        stance = str(payload.get("stance", "Neutral")).capitalize()
        if stance not in {"Bullish", "Bearish", "Neutral"}:
            stance = "Neutral"

        factors = payload.get("key_factors", [])
        if not isinstance(factors, list):
            factors = [str(factors)]

        score_raw = payload.get("score", 50.0)
        try:
            score = float(score_raw)
        except (TypeError, ValueError):
            score = 50.0
        score = max(0.0, min(100.0, score))

        return {
            "analyst_type": str(payload.get("analyst_type") or self.analyst_name),
            "ticker": str(payload.get("ticker") or ticker),
            "score": score,
            "stance": stance,
            "summary": str(payload.get("summary") or ""),
            "key_factors": [str(item) for item in factors][:10],
        }


def summarize_context_keys(context: dict[str, Any]) -> list[str]:
    """Utility used by tests/debug logs."""

    return sorted([str(key) for key in context.keys()])[:20]
