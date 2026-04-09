"""
来财 (Attract-wealth) — 风控经理

拦截并不合规、超额或者属于黑名单的交易请求。
"""
import logging
from src.core.trading_vm import AgentState
from src.core.trading_ledger import TradingLedger, LedgerEntry

logger = logging.getLogger(__name__)


class RiskManager:
    """系统风控阀门 (Rule-Based 为主)"""

    def __init__(self, max_single_stock_percent: float = 30.0):
        self.max_single_stock_percent = max_single_stock_percent
        self.ledger = TradingLedger()

    def check_risk(self, state: AgentState) -> dict:
        """同步方法执行硬性风控检查"""
        decision_data = state.get("trading_decision", {})
        action = decision_data.get("action", "HOLD")
        percentage = decision_data.get("percentage", 0)
        ticker = state.get("ticker", "")
        
        if action == "HOLD" or percentage <= 0:
            return {"risk_check": {"passed": True, "reason": "No Action"}}
            
        context = state.get("context", {})
        portfolio = context.get("portfolio", {})
        
        # 风控规则 1: 黑名单拦截 (示例)
        if ticker in ["300059", "600000"]:  # 伪示例黑名单
            self._log_rejection(state, "触发黑名单")
            return self._reject_state("触发黑名单退市警报")
            
        # 风控规则 2: 买入仓位限制
        if action == "BUY":
            if percentage > self.max_single_stock_percent:
                reason = f"试图动用 {percentage}% 资金，超名单一股票上限 ({self.max_single_stock_percent}%)"
                self._log_rejection(state, reason)
                return self._reject_state(reason)
                
            # TODO: 获取该股目前已持仓市值计算，如果 买入量 + 已持有 > 30% 总资产，也应拒绝
            
        logger.info(f"风控放行了 Trader 对于 {ticker} 的决定: {action} {percentage}%")
        return {"risk_check": {"passed": True, "reason": "All checks cleared"}}

    def _reject_state(self, reason: str) -> dict:
        return {
            "decision": "HOLD",  # 强行覆盖 Trader 决定
            "risk_check": {
                "passed": False,
                "reason": reason
            }
        }

    def _log_rejection(self, state: AgentState, reason: str):
        ticker = state["ticker"]
        self.ledger.record_entry(LedgerEntry(
            category="SYSTEM",
            action="RISK_REJECT",
            detail=f"Risk Rejection on {ticker}: {reason}",
            metadata={"ticker": ticker, "reason": reason}
        ))
