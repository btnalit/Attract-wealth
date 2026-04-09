"""
Trader agent: final decision maker after analyst/debate outputs.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from src.core.trading_vm import AgentState
from src.llm.openai_compat import create_deep_llm

logger = logging.getLogger(__name__)


class TradingAction(BaseModel):
    action: str = Field(description="BUY/SELL/HOLD")
    percentage: float = Field(description="0-100")
    reason: str = Field(description="Decision reason")
    confidence: float = Field(description="0-100")


class TraderAgent:
    """Chief trader with deep model."""

    def __init__(self):
        self.llm = create_deep_llm()

    async def decide(self, state: AgentState) -> dict[str, Any]:
        ticker = state["ticker"]
        debate = state.get("debate_results", {})
        reports = state.get("analysis_reports", {})
        context = state.get("context", {})
        portfolio_str = json.dumps(context.get("portfolio", {"balance": 0, "positions": {}}), ensure_ascii=False)

        prompt = (
            f"目标股票: {ticker}\n"
            f"==== 辩论结果 ====\n{json.dumps(debate, ensure_ascii=False, indent=2)}\n"
            f"==== 分析师摘要 ====\n"
        )
        for key, value in reports.items():
            summary = value.get("summary", "") if isinstance(value, dict) else getattr(value, "summary", "")
            prompt += f"[{key}]: {summary}\n"

        prompt += (
            f"\n==== 当前资金仓位 ====\n{portfolio_str}\n\n"
            "你是交易团队的最终拍板人，必须输出可执行结论。\n"
            "仅返回 JSON：\n"
            "{\n"
            '  "action": "BUY" | "SELL" | "HOLD",\n'
            '  "percentage": 0-100,\n'
            '  "reason": "简要原因",\n'
            '  "confidence": 0-100\n'
            "}"
        )

        try:
            resp = await self.llm.chat_simple(
                prompt,
                system="你是冷静、严格、可执行导向的量化交易决策引擎，只输出合法 JSON。",
                session_id=str(state.get("session_id", "")),
                agent_id="Trader_Agent",
            )
            clean = resp.replace("```json", "").replace("```", "").strip()
            data = json.loads(clean)
            parsed = TradingAction(
                action=str(data.get("action", "HOLD")).upper(),
                percentage=float(data.get("percentage", 0.0)),
                reason=str(data.get("reason", "")),
                confidence=float(data.get("confidence", 0.0)),
            )
            return {
                "decision": parsed.action,
                "confidence": parsed.confidence,
                "trading_decision": parsed.model_dump(),
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("Trader node failed: %s", exc)
            return {
                "decision": "HOLD",
                "confidence": 0.0,
                "trading_decision": {
                    "action": "HOLD",
                    "percentage": 0.0,
                    "reason": f"LLM fallback: {exc}",
                    "confidence": 0.0,
                },
            }
