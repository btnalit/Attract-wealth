"""
News/sentiment analyst（双轨：情绪数据 + 资金流规则 + LLM 解读）。

重构要点（A 股分析增强）：
- 注入新闻情绪 + 龙虎榜/资金流规则信号（情绪分析师兼任资金面观察）
- 把结构化信号交给 LLM 做综合解读
- LLM 失败时用规则层兜底
"""
from __future__ import annotations

import json

from src.agents.analysts.base import AnalystReport, BaseAnalyst
from src.agents.rules import money_flow_rules
from src.agents.rules.base import aggregate_signals, serialize_signals
from src.core.agent_state import AgentState


class NewsAnalyst(BaseAnalyst):
    analyst_name = "Sentiment_Agent"

    async def analyze(self, state: AgentState) -> AnalystReport:
        ticker = state["ticker"]
        context = state.get("context", {})
        news_data = context.get("news_sentiment", {})
        announcements = context.get("announcements") or []

        # 1. 跑资金流规则（情绪分析师兼任资金面观察）
        signals = money_flow_rules.evaluate(context)
        rule_summary = aggregate_signals(signals)

        # 2. metrics：新闻情绪 + 资金流概览 + 公告摘要
        metrics = {
            "news_status": news_data.get("status") if isinstance(news_data, dict) else "no_news",
            "sentiment_score": news_data.get("sentiment_score") if isinstance(news_data, dict) else None,
            "news_summary": news_data.get("summary") if isinstance(news_data, dict) else "",
            "rule_score": rule_summary["score"],
            "main_net": (context.get("money_flow") or {}).get("main_net") if isinstance(context.get("money_flow"), dict) else None,
            "announcement_count": len(announcements) if isinstance(announcements, list) else 0,
            "latest_announcement": announcements[0].get("title", "") if isinstance(announcements, list) and announcements else "",
        }

        has_news = isinstance(news_data, dict) and news_data.get("status") not in ("no_news", None)
        has_announcements = isinstance(announcements, list) and len(announcements) > 0
        if not has_news and not has_announcements and not signals:
            return AnalystReport(
                analyst_type=self.analyst_name,
                ticker=ticker,
                score=50.0,
                stance="Neutral",
                summary="近期缺少有效新闻/公告，且无资金流信号，情绪面保持中性。",
                key_factors=["No news", "No announcements", "No money flow"],
            )

        # 3. 构造 LLM 上下文（新闻 + 公告 + 规则信号）
        announcements_str = ""
        if has_announcements:
            announcements_str = "\n近期公告（重大事项/业绩预告/增减持等，请判断对情绪的影响）:\n"
            for ann in announcements[:5]:
                announcements_str += f"- [{ann.get('date', '')}] {ann.get('title', '')} ({ann.get('type', '')})\n"

        context_str = (
            f"新闻情绪:\n{json.dumps(news_data, ensure_ascii=False, indent=2)}\n"
            f"{announcements_str}\n"
            f"{serialize_signals(signals)}"
        )

        system_prompt = (
            "你是A股新闻情绪分析师。请综合新闻情绪、近期公告（重大事项/业绩预告/增减持）、"
            "资金流规则信号，评估短线情绪偏多/偏空/中性并输出结构化结果。"
            "公告比新闻更具权威性，业绩预增/增持偏多，预减/减持偏空。"
            "若新闻为空但公告或资金流信号明确，以公告或资金流信号为准。"
        )

        return await self._ask_llm_for_report(
            ticker=ticker,
            context=context_str,
            system_prompt=system_prompt,
            session_id=str(state.get("session_id", "")),
            signals=[s.to_dict() for s in signals],
            metrics=metrics,
            rule_confidence=rule_summary["confidence"],
        )
