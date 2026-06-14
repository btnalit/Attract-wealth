"""
Technical analyst（双轨：规则引擎 + LLM 解读）。

重构要点（A 股分析增强）：
- 先跑趋势/量价规则引擎，拿到结构化信号
- 把规则结论（而非原始数据）交给 LLM 做综合解读
- LLM 失败时用规则层分数兜底
- AnalystReport 携带 signals/metrics 供前端展示
"""
from __future__ import annotations

import json

from src.agents.analysts.base import AnalystReport, BaseAnalyst
from src.agents.rules import trend_rules, volume_price_rules
from src.agents.rules.base import aggregate_signals, serialize_signals
from src.core.agent_state import AgentState


class TechnicalAnalyst(BaseAnalyst):
    analyst_name = "Technical_Agent"

    async def analyze(self, state: AgentState) -> AnalystReport:
        ticker = state["ticker"]
        context = state.get("context", {})
        tech_data = context.get("technical_indicators", {})

        if not tech_data:
            return AnalystReport(
                analyst_type=self.analyst_name,
                ticker=ticker,
                score=50.0,
                stance="Neutral",
                summary="无有效技术指标数据，暂不形成交易信号。",
                key_factors=["No technical data"],
            )

        # 1. 跑规则引擎（确定性结论）
        signals = []
        signals.extend(trend_rules.evaluate(tech_data))
        signals.extend(volume_price_rules.evaluate(context))
        rule_summary = aggregate_signals(signals)

        # 2. 构造给 LLM 的上下文：规则结论 + 关键指标快照
        metrics = {
            "MA5": tech_data.get("MA5"),
            "MA20": tech_data.get("MA20"),
            "RSI_14": tech_data.get("RSI_14"),
            "MACD_DIF": tech_data.get("MACD_DIF"),
            "MACD_HIST": tech_data.get("MACD_HIST"),
            "trend_signal": context.get("trend_signal"),
            "rule_score": rule_summary["score"],
        }
        context_str = (
            f"关键指标:\n{json.dumps(metrics, ensure_ascii=False, indent=2)}\n\n"
            f"{serialize_signals(signals)}"
        )

        system_prompt = (
            "你是A股技术分析师。规则引擎已产出结构化信号（均线/MACD/量价），"
            "请综合判断短线倾向，给出评分(0-100，越高越看多)和关键驱动因素。"
            "你的结论应与规则信号的大方向一致，但可调整强度。"
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
