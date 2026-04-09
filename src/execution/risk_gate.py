"""
Risk gate for all execution channels.

All orders must pass these hard rules before reaching any broker.
"""
from __future__ import annotations

import time
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

from src.execution.base import OrderRequest, OrderSide


@dataclass
class RiskViolation:
    rule: str
    description: str
    value: float = 0.0
    limit: float = 0.0
    timestamp: float = field(default_factory=time.time)


@dataclass
class RiskAlert:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    rule: str = ""
    severity: str = "warning"
    description: str = ""
    blocking: bool = True
    context: dict[str, Any] = field(default_factory=dict)


class RiskGate:
    # Hard-coded rules, cannot be bypassed by config
    MAX_SINGLE_ORDER_RATIO = 0.20
    MAX_DAILY_LOSS_RATIO = 0.05
    MAX_POSITION_CONCENTRATION = 0.30
    MAX_ORDERS_PER_MINUTE = 5
    MIN_SIMULATION_DAYS = 7
    ALERT_HISTORY_LIMIT = 500

    def __init__(self):
        self._violations: list[RiskViolation] = []
        self._alerts: list[RiskAlert] = []
        self._rule_hits: Counter[str] = Counter()

        self._order_timestamps: list[float] = []
        self._daily_loss: float = 0.0
        self._trading_paused: bool = False
        self._pause_reason: str = ""

        self._checks_total = 0
        self._checks_passed = 0
        self._checks_rejected = 0
        self._last_check_at = 0.0

    def check_order(
        self,
        request: OrderRequest,
        total_assets: float,
        current_positions: dict[str, float],
        daily_pnl: float,
        is_live: bool = False,
        simulation_days: int = 0,
    ) -> tuple[bool, list[RiskViolation]]:
        self._checks_total += 1
        self._last_check_at = time.time()

        violations: list[RiskViolation] = []
        context = {
            "ticker": request.ticker,
            "side": request.side.value if hasattr(request.side, "value") else str(request.side),
            "price": request.price,
            "quantity": request.quantity,
            "total_assets": total_assets,
            "daily_pnl": daily_pnl,
            "is_live": is_live,
            "simulation_days": simulation_days,
        }

        if self._trading_paused:
            violations.append(
                RiskViolation(rule="TRADING_PAUSED", description=f"交易已暂停: {self._pause_reason}")
            )
            return self._finalize_rejection(violations, context)

        order_amount = request.price * request.quantity
        if total_assets > 0:
            ratio = order_amount / total_assets
            if ratio > self.MAX_SINGLE_ORDER_RATIO:
                violations.append(
                    RiskViolation(
                        rule="SINGLE_ORDER_LIMIT",
                        description=(
                            f"单笔金额 {order_amount:.0f} 占总资产 {ratio:.1%}，"
                            f"超过 {self.MAX_SINGLE_ORDER_RATIO:.0%} 限制"
                        ),
                        value=ratio,
                        limit=self.MAX_SINGLE_ORDER_RATIO,
                    )
                )

        if total_assets > 0 and daily_pnl < 0:
            loss_ratio = abs(daily_pnl) / total_assets
            if loss_ratio >= self.MAX_DAILY_LOSS_RATIO:
                self._trading_paused = True
                self._pause_reason = f"日亏损达到 {loss_ratio:.1%}，自动暂停至次日"
                violations.append(
                    RiskViolation(
                        rule="DAILY_LOSS_LIMIT",
                        description=self._pause_reason,
                        value=loss_ratio,
                        limit=self.MAX_DAILY_LOSS_RATIO,
                    )
                )

        if request.side == OrderSide.BUY and total_assets > 0:
            existing = current_positions.get(request.ticker, 0.0)
            concentration = (existing + order_amount) / total_assets
            if concentration > self.MAX_POSITION_CONCENTRATION:
                violations.append(
                    RiskViolation(
                        rule="POSITION_CONCENTRATION",
                        description=(
                            f"{request.ticker} 持仓将达 {concentration:.1%}，"
                            f"超过 {self.MAX_POSITION_CONCENTRATION:.0%} 限制"
                        ),
                        value=concentration,
                        limit=self.MAX_POSITION_CONCENTRATION,
                    )
                )

        now = time.time()
        self._order_timestamps = [t for t in self._order_timestamps if now - t < 60]
        if len(self._order_timestamps) >= self.MAX_ORDERS_PER_MINUTE:
            violations.append(
                RiskViolation(
                    rule="ORDER_FREQUENCY",
                    description=(
                        f"1 分钟内已下单 {len(self._order_timestamps)} 次，"
                        f"超过 {self.MAX_ORDERS_PER_MINUTE} 次限制"
                    ),
                    value=float(len(self._order_timestamps)),
                    limit=float(self.MAX_ORDERS_PER_MINUTE),
                )
            )

        if is_live and simulation_days < self.MIN_SIMULATION_DAYS:
            violations.append(
                RiskViolation(
                    rule="SIMULATION_REQUIRED",
                    description=(
                        f"实盘前需先模拟 >= {self.MIN_SIMULATION_DAYS} 天，"
                        f"当前仅 {simulation_days} 天"
                    ),
                    value=float(simulation_days),
                    limit=float(self.MIN_SIMULATION_DAYS),
                )
            )

        if violations:
            return self._finalize_rejection(violations, context)

        self._checks_passed += 1
        self._order_timestamps.append(now)
        return True, []

    def _finalize_rejection(
        self,
        violations: list[RiskViolation],
        context: dict[str, Any],
    ) -> tuple[bool, list[RiskViolation]]:
        self._checks_rejected += 1
        self._violations.extend(violations)
        for violation in violations:
            self._rule_hits[violation.rule] += 1
            self._append_alert(violation, context=context)
            try:
                from src.routers.stream import publish_log
                publish_log("RISK", f"Risk Violation: {violation.rule} - {violation.description}", level="error")
            except Exception:
                pass
        return False, violations

    def _append_alert(self, violation: RiskViolation, context: dict[str, Any]):
        severity = "critical" if violation.rule in {"TRADING_PAUSED", "DAILY_LOSS_LIMIT"} else "warning"
        self._alerts.append(
            RiskAlert(
                rule=violation.rule,
                severity=severity,
                description=violation.description,
                blocking=True,
                context={
                    **context,
                    "value": violation.value,
                    "limit": violation.limit,
                },
            )
        )
        if len(self._alerts) > self.ALERT_HISTORY_LIMIT:
            self._alerts = self._alerts[-self.ALERT_HISTORY_LIMIT :]

    def reset_daily(self):
        self._trading_paused = False
        self._pause_reason = ""
        self._daily_loss = 0.0
        self._order_timestamps.clear()

    def get_recent_alerts(self, limit: int = 50) -> list[dict[str, Any]]:
        n = max(1, int(limit))
        return [asdict(alert) for alert in self._alerts[-n:]][::-1]

    def get_metrics(self) -> dict[str, Any]:
        pass_rate = (self._checks_passed / self._checks_total) if self._checks_total > 0 else 1.0
        latest_alert = self._alerts[-1] if self._alerts else None
        return {
            "checks_total": self._checks_total,
            "checks_passed": self._checks_passed,
            "checks_rejected": self._checks_rejected,
            "pass_rate": round(pass_rate, 4),
            "is_paused": self._trading_paused,
            "pause_reason": self._pause_reason,
            "rule_hits": dict(self._rule_hits),
            "alerts_count": len(self._alerts),
            "last_check_at": self._last_check_at,
            "latest_alert": asdict(latest_alert) if latest_alert else None,
        }

    @property
    def violations_history(self) -> list[RiskViolation]:
        return self._violations.copy()

    @property
    def is_paused(self) -> bool:
        return self._trading_paused
