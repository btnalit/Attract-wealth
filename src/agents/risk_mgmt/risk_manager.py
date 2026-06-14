"""
Rule-based risk manager used inside the agent trading graph.
"""
from __future__ import annotations

import logging
from typing import Any

from src.core.trading_ledger import LedgerEntry, TradingLedger
from src.core.agent_state import AgentState

logger = logging.getLogger(__name__)


class RiskManager:
    """Risk gate for agent decision output."""

    def __init__(self, max_single_stock_percent: float = 30.0):
        self.max_single_stock_percent = float(max_single_stock_percent)
        self.ledger = TradingLedger()

    @staticmethod
    def _to_float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _estimate_existing_position_percent(self, portfolio: dict[str, Any], ticker: str) -> float:
        total_assets = self._to_float(portfolio.get("total_assets", 0.0))
        if total_assets <= 0:
            return 0.0

        positions = portfolio.get("positions", {}) if isinstance(portfolio.get("positions", {}), dict) else {}
        position_info = positions.get(str(ticker or ""), {}) if isinstance(positions, dict) else {}
        market_value = self._to_float(position_info.get("market_value", 0.0))
        if market_value <= 0:
            return 0.0

        return market_value / total_assets * 100.0

    def check_risk(self, state: AgentState) -> dict:
        decision_data = state.get("trading_decision", {}) if isinstance(state.get("trading_decision", {}), dict) else {}
        action = str(decision_data.get("action", "HOLD")).upper()
        requested_percent = self._to_float(decision_data.get("percentage", 0.0))
        ticker = str(state.get("ticker", "")).strip()

        if action == "HOLD" or requested_percent <= 0:
            return {"risk_check": {"passed": True, "reason": "No Action"}}

        context = state.get("context", {}) if isinstance(state.get("context", {}), dict) else {}
        portfolio = context.get("portfolio", {}) if isinstance(context.get("portfolio", {}), dict) else {}

        # Rule 1: hard blacklist check.
        if ticker in {"300059", "600000"}:
            reason = "Ticker is in blacklist"
            self._log_rejection(state, reason)
            return self._reject_state(reason)

        # Rule 2: per-order position ratio limit.
        if action == "BUY" and requested_percent > self.max_single_stock_percent:
            reason = (
                f"Requested position {requested_percent:.2f}% exceeds max single-stock limit "
                f"{self.max_single_stock_percent:.2f}%"
            )
            self._log_rejection(state, reason)
            return self._reject_state(reason)

        # Rule 3: existing position + requested buy should not exceed single-stock limit.
        # G7-6：无组合数据（total_assets<=0 或缺失）时无法评估现有集中度。
        # 处理策略：能获取组合数据时做"叠加"校验；缺失数据时保守放行（graph 层是
        # 软风控），并记 WARNING 让降级可观测 —— 硬层 RiskGate（有并发锁 + 硬白名单）
        # 仍会强制真正的持仓集中度红线，不会因 graph 层放行而失守。
        if action == "BUY":
            existing_percent = self._estimate_existing_position_percent(portfolio, ticker)
            total_assets = self._to_float(portfolio.get("total_assets", 0.0))
            if total_assets > 0:
                projected_percent = requested_percent + existing_percent
                if projected_percent > self.max_single_stock_percent:
                    reason = (
                        f"Projected position {projected_percent:.2f}% exceeds max single-stock limit "
                        f"{self.max_single_stock_percent:.2f}% (existing {existing_percent:.2f}% + requested {requested_percent:.2f}%)"
                    )
                    self._log_rejection(state, reason)
                    return self._reject_state(reason)
            else:
                logger.warning(
                    "RiskManager: portfolio total_assets missing/zero for ticker=%s, "
                    "concentration check skipped (Rule 3 degraded). Hard layer RiskGate still enforces.",
                    ticker,
                )

        # ===== A 股特有风控规则 =====
        # T+1 卖出约束（独立于 ashare_flags，看持仓 available 字段）
        t1_check = self._check_t_plus_1(ticker, action, portfolio)
        if t1_check is not None:
            self._log_rejection(state, t1_check["risk_check"]["reason"])
            return t1_check

        # ST/涨停/停牌（基于 ashare_flags，flags 为空时软跳过）
        ashare_check = self._check_ashare_rules(state, ticker, action)
        if ashare_check is not None:
            return ashare_check

        logger.info("Risk check passed: ticker=%s action=%s requested=%.2f%%", ticker, action, requested_percent)
        return {"risk_check": {"passed": True, "reason": "All checks cleared"}}

    def _check_t_plus_1(
        self,
        ticker: str,
        action: str,
        portfolio: dict[str, Any],
    ) -> dict | None:
        """T+1 卖出约束：当日买入的股票不能卖（available < quantity）。

        独立于 ashare_flags，直接查持仓快照。返回 None 表示通过。
        """
        if action != "SELL":
            return None
        positions = portfolio.get("positions", {}) if isinstance(portfolio.get("positions", {}), dict) else {}
        position_info = positions.get(str(ticker or ""), {})
        if not isinstance(position_info, dict) or not position_info:
            return None
        quantity = self._to_float(position_info.get("quantity", 0))
        available = self._to_float(position_info.get("available", quantity))
        if quantity > 0 and available <= 0:
            reason = f"A股风控：T+1 约束，{ticker} 当日买入不可卖出（quantity={quantity}, available={available}）"
            return self._reject_state(reason)
        return None

    def _check_ashare_rules(
        self,
        state: AgentState,
        ticker: str,
        action: str,
    ) -> dict | None:
        """A 股特有风控：ST / 涨停 / 停牌。

        基于 context['ashare_flags']，flags 为空时软跳过（不阻断）。
        返回 None 表示通过。
        """
        context = state.get("context", {}) if isinstance(state.get("context", {}), dict) else {}
        flags_data = context.get("ashare_flags", {})
        if not isinstance(flags_data, dict) or not flags_data:
            return None

        flags = flags_data.get("flags") or []
        if not isinstance(flags, list):
            flags = []
        flag_set = set(str(f).upper() for f in flags)
        is_st = bool(flags_data.get("is_st")) or "ST" in flag_set
        limit_up = bool(flags_data.get("limit_up")) or "LIMIT_UP" in flag_set
        suspended = bool(flags_data.get("suspended")) or "SUSPENDED" in flag_set

        # 停牌拦截（买卖都拦）
        if suspended:
            reason = f"A股风控：{ticker} 当前停牌，无法交易"
            self._log_rejection(state, reason)
            return self._reject_state(reason)

        # ST 拦截买入（可配置开关，默认拦截）
        if action == "BUY" and is_st:
            if self._env_true("RISK_BLOCK_ST_BUY", default=True):
                reason = f"A股风控：{ticker} 为 ST 股票，存在退市风险，买入被拦截（设置 RISK_BLOCK_ST_BUY=false 可关闭）"
                self._log_rejection(state, reason)
                return self._reject_state(reason)

        # 涨停板买入拦截（涨停时买不进，拦截避免无效委托）
        if action == "BUY" and limit_up:
            reason = f"A股风控：{ticker} 当日涨停，买入委托无法成交，已拦截"
            self._log_rejection(state, reason)
            return self._reject_state(reason)

        return None

    @staticmethod
    def _env_true(name: str, *, default: bool = False) -> bool:
        import os
        raw = os.getenv(name)
        if raw is None:
            return default
        return raw.strip().lower() in {"1", "true", "yes", "on"}

    def _reject_state(self, reason: str) -> dict:
        return {
            "decision": "HOLD",
            "risk_check": {
                "passed": False,
                "reason": reason,
            },
        }

    def _log_rejection(self, state: AgentState, reason: str):
        ticker = str(state.get("ticker", ""))
        self.ledger.record_entry(
            LedgerEntry(
                category="SYSTEM",
                action="RISK_REJECT",
                detail=f"Risk rejection on {ticker}: {reason}",
                metadata={"ticker": ticker, "reason": reason},
            )
        )
