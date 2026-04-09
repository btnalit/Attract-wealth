"""
Technical analyst.
"""
from __future__ import annotations

import json

from src.agents.analysts.base import AnalystReport, BaseAnalyst
from src.core.trading_vm import AgentState


class TechnicalAnalyst(BaseAnalyst):
    analyst_name = "Technical_Agent"

    async def analyze(self, state: AgentState) -> AnalystReport:
        ticker = state["ticker"]
        tech_data = state.get("context", {}).get("technical_indicators", {})

        if not tech_data:
            return AnalystReport(
                analyst_type=self.analyst_name,
                ticker=ticker,
                score=50.0,
                stance="Neutral",
                summary="无有效技术指标数据，暂不形成交易信号。",
                key_factors=["No technical data"],
            )

        system_prompt = (
            "你是A股技术分析师。请结合趋势、量价、波动指标输出短线倾向，"
            "并给出关键驱动因素。"
        )
        context_str = json.dumps(tech_data, ensure_ascii=False, indent=2)
        return await self._ask_llm_for_report(
            ticker=ticker,
            context=context_str,
            system_prompt=system_prompt,
            session_id=str(state.get("session_id", "")),
        )
