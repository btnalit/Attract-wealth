"""
Fundamental analyst（双轨：结构化数据注入 + LLM 解读）。

重构要点（A 股分析增强）：
- 把财务摘要 + 板块信息 + 估值结构化注入 prompt（而非单一 fundamentals）
- 携带 metrics 供前端展示
- LLM 失败时保持中性兜底（基本面规则化复杂度高，暂不强加规则）
"""
from __future__ import annotations

import json

from src.agents.analysts.base import AnalystReport, BaseAnalyst
from src.core.agent_state import AgentState


class FundamentalAnalyst(BaseAnalyst):
    analyst_name = "Fundamental_Agent"

    async def analyze(self, state: AgentState) -> AnalystReport:
        ticker = state["ticker"]
        context = state.get("context", {})
        financials = context.get("financials", {})
        sector_info = context.get("sector_info", {})
        margin = context.get("margin", {})

        # 向后兼容：老接口可能直接塞 fundamentals
        legacy = context.get("fundamentals", {})
        has_data = any(bool(x) for x in (financials, sector_info, margin, legacy))

        if not has_data:
            return AnalystReport(
                analyst_type=self.analyst_name,
                ticker=ticker,
                score=50.0,
                stance="Neutral",
                summary="无有效基本面数据，暂不形成方向性结论。",
                key_factors=["No fundamental data"],
            )

        # 结构化 metrics（供前端展示 + LLM 上下文）
        metrics = {
            "financials": financials or legacy,
            "industry": sector_info.get("industry") if isinstance(sector_info, dict) else "",
            "concept": sector_info.get("concept") if isinstance(sector_info, dict) else "",
            "total_market_cap": sector_info.get("total_market_cap") if isinstance(sector_info, dict) else None,
            "finance_balance": margin.get("finance_balance") if isinstance(margin, dict) else None,
        }

        system_prompt = (
            "你是A股基本面分析师。请依据财务指标、估值、行业景气度、融资融券给出结构化结论。"
            "财务摘要可能字段不全，不要编造不存在的数据。"
        )
        context_str = json.dumps(metrics, ensure_ascii=False, indent=2)

        return await self._ask_llm_for_report(
            ticker=ticker,
            context=context_str,
            system_prompt=system_prompt,
            session_id=str(state.get("session_id", "")),
            metrics=metrics,
        )
