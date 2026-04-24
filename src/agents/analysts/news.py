"""
News/sentiment analyst.
"""
from __future__ import annotations

import json

from src.agents.analysts.base import AnalystReport, BaseAnalyst
from src.core.agent_state import AgentState


class NewsAnalyst(BaseAnalyst):
    analyst_name = "Sentiment_Agent"

    async def analyze(self, state: AgentState) -> AnalystReport:
        ticker = state["ticker"]
        news_data = state.get("context", {}).get("news_sentiment", {})

        if not news_data or news_data.get("status") == "no_news":
            return AnalystReport(
                analyst_type=self.analyst_name,
                ticker=ticker,
                score=50.0,
                stance="Neutral",
                summary="近期缺少有效新闻样本，情绪面保持中性。",
                key_factors=["No news"],
            )

        system_prompt = (
            "你是A股新闻情绪分析师。请根据新闻主题与情绪强度，"
            "评估短线情绪偏多/偏空/中性并输出结构化结果。"
        )
        context_str = json.dumps(news_data, ensure_ascii=False, indent=2)
        return await self._ask_llm_for_report(
            ticker=ticker,
            context=context_str,
            system_prompt=system_prompt,
            session_id=str(state.get("session_id", "")),
        )
