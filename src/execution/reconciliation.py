"""
来财 对账引擎。

核对维度：
- 账户现金
- 持仓数量
"""
from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from src.core.trading_ledger import LedgerEntry, TradingLedger
from src.execution.base import AccountBalance, BaseBroker, Position


@dataclass
class ReconciliationIssue:
    category: str
    key: str
    broker_value: float
    ledger_value: float
    delta: float
    detail: str
    severity: str = "warn"  # warn/critical


@dataclass
class ReconciliationReport:
    timestamp: float = field(default_factory=time.time)
    channel: str = ""
    status: str = "matched"  # matched/mismatch/error
    issues_count: int = 0
    issues: list[ReconciliationIssue] = field(default_factory=list)
    broker_snapshot: dict[str, Any] = field(default_factory=dict)
    ledger_snapshot: dict[str, Any] = field(default_factory=dict)
    alert_level: str = "none"  # none/warn/critical
    action: str = "record"  # record/block
    code: str = "RECON_OK"  # RECON_OK/RECON_WARN/RECON_BLOCK/RECON_ERROR

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "channel": self.channel,
            "status": self.status,
            "issues_count": self.issues_count,
            "issues": [asdict(issue) for issue in self.issues],
            "broker_snapshot": self.broker_snapshot,
            "ledger_snapshot": self.ledger_snapshot,
            "alert_level": self.alert_level,
            "action": self.action,
            "code": self.code,
        }


class ReconciliationEngine:
    """
    执行持仓/资金对账。

    对账策略：
    - 仓位: ticker 维度逐只核对数量
    - 现金: broker available_cash 与 ledger 重建现金核对
    """

    def __init__(self, broker: BaseBroker, cash_tolerance: float = 1.0, quantity_tolerance: int = 0):
        self.broker = broker
        self.cash_tolerance = float(cash_tolerance)
        self.quantity_tolerance = int(quantity_tolerance)
        self.cash_warn_threshold = float(os.getenv("RECON_CASH_WARN", "3000"))
        self.cash_block_threshold = float(os.getenv("RECON_CASH_BLOCK", "20000"))
        self.position_warn_threshold = int(os.getenv("RECON_POSITION_WARN", "200"))
        self.position_block_threshold = int(os.getenv("RECON_POSITION_BLOCK", "1000"))

    async def run(self, initial_cash: float = 1_000_000.0) -> dict[str, Any]:
        report = ReconciliationReport(channel=getattr(self.broker, "channel_name", "unknown"))
        try:
            broker_balance = await self.broker.get_balance()
            broker_positions = await self.broker.get_positions()
            broker_snapshot = self._build_broker_snapshot(broker_balance, broker_positions)
            try:
                ledger_snapshot = TradingLedger.build_portfolio_snapshot(
                    initial_cash=initial_cash,
                    channel=report.channel,
                )
            except TypeError:
                # Backward compatibility for tests/mocks that still expose
                # build_portfolio_snapshot(initial_cash=...) only.
                ledger_snapshot = TradingLedger.build_portfolio_snapshot(initial_cash=initial_cash)

            report.broker_snapshot = broker_snapshot
            report.ledger_snapshot = ledger_snapshot
            report.issues.extend(self._compare_cash(broker_snapshot, ledger_snapshot))
            report.issues.extend(self._compare_positions(broker_snapshot, ledger_snapshot))
            report.issues_count = len(report.issues)
            report.status = "matched" if report.issues_count == 0 else "mismatch"
            self._classify_alert(report)
        except Exception as exc:  # noqa: BLE001
            report.status = "error"
            report.alert_level = "critical"
            report.action = "block"
            report.code = "RECON_ERROR"
            report.issues.append(
                ReconciliationIssue(
                    category="system",
                    key="reconciliation_error",
                    broker_value=0.0,
                    ledger_value=0.0,
                    delta=0.0,
                    detail=str(exc),
                    severity="critical",
                )
            )
            report.issues_count = 1

        payload = report.to_dict()
        TradingLedger.record_reconciliation(payload)
        TradingLedger.record_entry(
            LedgerEntry(
                category="SYSTEM",
                action="RECONCILIATION",
                detail=f"channel={report.channel} status={report.status} issues={report.issues_count}",
                metadata={
                    "channel": report.channel,
                    "status": report.status,
                    "issues_count": report.issues_count,
                    "alert_level": report.alert_level,
                    "action": report.action,
                    "code": report.code,
                },
            )
        )
        return payload

    def _build_broker_snapshot(self, balance: AccountBalance, positions: list[Position]) -> dict[str, Any]:
        return {
            "cash": float(balance.available_cash or 0.0),
            "positions": {pos.ticker: int(pos.quantity or 0) for pos in positions if pos.ticker},
        }

    def _compare_cash(self, broker_snapshot: dict[str, Any], ledger_snapshot: dict[str, Any]) -> list[ReconciliationIssue]:
        broker_cash = float(broker_snapshot.get("cash", 0.0))
        ledger_cash = float(ledger_snapshot.get("cash", 0.0))
        delta = broker_cash - ledger_cash
        abs_delta = abs(delta)
        if abs_delta <= self.cash_tolerance:
            return []
        severity = "critical" if abs_delta >= self.cash_block_threshold else "warn"
        return [
            ReconciliationIssue(
                category="cash",
                key="available_cash",
                broker_value=broker_cash,
                ledger_value=ledger_cash,
                delta=delta,
                detail=f"现金偏差超过容忍阈值 {self.cash_tolerance}",
                severity=severity,
            )
        ]

    def _compare_positions(
        self,
        broker_snapshot: dict[str, Any],
        ledger_snapshot: dict[str, Any],
    ) -> list[ReconciliationIssue]:
        broker_positions = broker_snapshot.get("positions", {})
        ledger_positions = ledger_snapshot.get("positions", {})

        all_tickers = set(broker_positions.keys()) | set(ledger_positions.keys())
        issues: list[ReconciliationIssue] = []
        for ticker in sorted(all_tickers):
            broker_qty = int(broker_positions.get(ticker, 0))
            ledger_qty = int(ledger_positions.get(ticker, 0))
            delta = broker_qty - ledger_qty
            abs_delta = abs(delta)
            if abs_delta <= self.quantity_tolerance:
                continue
            severity = "critical" if abs_delta >= self.position_block_threshold else "warn"
            issues.append(
                ReconciliationIssue(
                    category="position",
                    key=ticker,
                    broker_value=float(broker_qty),
                    ledger_value=float(ledger_qty),
                    delta=float(delta),
                    detail=f"{ticker} 持仓数量不一致",
                    severity=severity,
                )
            )
        return issues

    def _classify_alert(self, report: ReconciliationReport):
        if report.status == "matched":
            report.alert_level = "none"
            report.action = "record"
            report.code = "RECON_OK"
            return

        has_critical = any(item.severity == "critical" for item in report.issues)
        if has_critical:
            report.alert_level = "critical"
            report.action = "block"
            report.code = "RECON_BLOCK"
            return

        report.alert_level = "warn"
        report.action = "record"
        report.code = "RECON_WARN"
