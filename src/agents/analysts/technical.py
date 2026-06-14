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
from src.agents.rules import sector_rules, trend_rules, volume_price_rules
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

        # 1. 跑规则引擎（确定性结论）：趋势(单点+序列) + 量价 + 板块联动
        signals = []
        signals.extend(trend_rules.evaluate(tech_data))
        signals.extend(trend_rules.evaluate_with_history(context.get("kline_recent") or []))
        signals.extend(volume_price_rules.evaluate(context))
        signals.extend(sector_rules.evaluate(context))
        # 数据过时/不全时降低置信度
        freshness = context.get("data_freshness") or {}
        stale_penalty = float(freshness.get("stale_penalty", 0.0)) if isinstance(freshness, dict) else 0.0
        rule_summary = aggregate_signals(signals, stale_penalty=stale_penalty)

        # P2-1：把规则信号落盘到 signal_log（软失败，不影响主链路）
        self._persist_signals(ticker, context, signals)

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

    @staticmethod
    def _persist_signals(
        ticker: str,
        context: dict,
        signals: list,
    ) -> None:
        """P2-1：把规则信号落盘到 signal_log 供未来在线准确率跟踪。

        软失败：任何异常都不影响主分析链路（信号持久化是旁路观测）。
        """
        if not signals:
            return
        try:
            from src.dao.signal_log_dao import get_signal_log_dao

            # 信号当日 = kline 最新日期，无则用今天
            kline_recent = context.get("kline_recent") or []
            signal_date = ""
            close_at_signal = None
            if kline_recent:
                last = kline_recent[-1] if isinstance(kline_recent[-1], dict) else {}
                signal_date = str(last.get("date", ""))[:10]
                close_at_signal = last.get("close")
            if not signal_date:
                from datetime import date
                signal_date = date.today().isoformat()

            dao = get_signal_log_dao()
            dao.log_signals(
                ticker=ticker,
                signal_date=signal_date,
                signals=[s.to_dict() if hasattr(s, "to_dict") else s for s in signals],
                close_at_signal=float(close_at_signal) if close_at_signal else None,
                analyst_type="Technical_Agent",
            )
        except Exception:  # noqa: BLE001
            # 持久化是旁路功能，绝不能拖垮主分析链路
            import logging
            logging.getLogger(__name__).debug(
                "signal_log 持久化失败（已忽略）", exc_info=True
            )
