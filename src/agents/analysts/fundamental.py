"""
Fundamental analyst.
"""
from __future__ import annotations

import json

from src.agents.analysts.base import AnalystReport, BaseAnalyst
from src.core.agent_state import AgentState


class FundamentalAnalyst(BaseAnalyst):
    analyst_name = "Fundamental_Agent"

    async def analyze(self, state: AgentState) -> AnalystReport:
        ticker = state["ticker"]
        market_info = state.get("context", {}).get("fundamentals", {})

        if not market_info:
            return AnalystReport(
                analyst_type=self.analyst_name,
                ticker=ticker,
                score=50.0,
                stance="Neutral",
                summary="无有效基本面数据，暂不形成方向性结论。",
                key_factors=["No fundamental data"],
            )

        system_prompt = (
            "你是A股基本面分析师。请依据估值、盈利、行业景气度给出结构化结论，"
            "不要编造不存在的数据。"
        )
        context_str = json.dumps(market_info, ensure_ascii=False, indent=2)
        return await self._ask_llm_for_report(
            ticker=ticker,
            context=context_str,
            system_prompt=system_prompt,
            session_id=str(state.get("session_id", "")),
        )
