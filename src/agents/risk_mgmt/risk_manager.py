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
        if action == "BUY":
            existing_percent = self._estimate_existing_position_percent(portfolio, ticker)
            projected_percent = requested_percent + existing_percent
            if projected_percent > self.max_single_stock_percent:
                reason = (
                    f"Projected position {projected_percent:.2f}% exceeds max single-stock limit "
                    f"{self.max_single_stock_percent:.2f}% (existing {existing_percent:.2f}% + requested {requested_percent:.2f}%)"
                )
                self._log_rejection(state, reason)
                return self._reject_state(reason)

        logger.info("Risk check passed: ticker=%s action=%s requested=%.2f%%", ticker, action, requested_percent)
        return {"risk_check": {"passed": True, "reason": "All checks cleared"}}

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
