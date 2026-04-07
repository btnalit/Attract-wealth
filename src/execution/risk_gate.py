"""
来财 风控门 — 实盘交易必经的安全关卡

所有交易指令在到达交易通道之前，必须通过风控门审核。
风控红线为硬编码，不可通过配置文件绕过。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from src.execution.base import OrderRequest, OrderSide


@dataclass
class RiskViolation:
    """风控违规记录"""
    rule: str
    description: str
    value: float = 0.0
    limit: float = 0.0
    timestamp: float = field(default_factory=time.time)


class RiskGate:
    """
    风控门 — 6 条硬编码红线

    红线规则（不可通过配置绕过）：
    1. 单笔交易金额 ≤ 总资产 20%
    2. 单日亏损达 5% → 自动暂停至次日
    3. 单只股票持仓 ≤ 总资产 30%
    4. 每分钟下单次数 ≤ 5 次
    5. 首次实盘 → 必须模拟运行 ≥ 7 天
    6. 所有下单写入不可删改的审计日志
    """

    # ===== 硬编码红线 (HARD-CODED, 不可配置) =====
    MAX_SINGLE_ORDER_RATIO = 0.20       # 单笔 ≤ 总资产 20%
    MAX_DAILY_LOSS_RATIO = 0.05         # 日亏损 ≤ 5%
    MAX_POSITION_CONCENTRATION = 0.30   # 单只 ≤ 总资产 30%
    MAX_ORDERS_PER_MINUTE = 5           # 每分钟 ≤ 5 单
    MIN_SIMULATION_DAYS = 7             # 模拟最少 7 天
    # ================================================

    def __init__(self):
        self._violations: list[RiskViolation] = []
        self._order_timestamps: list[float] = []
        self._daily_loss: float = 0.0
        self._trading_paused: bool = False
        self._pause_reason: str = ""
        self._simulation_days: int = 0

    def check_order(
        self,
        request: OrderRequest,
        total_assets: float,
        current_positions: dict[str, float],  # ticker -> market_value
        daily_pnl: float,
        is_live: bool = False,
        simulation_days: int = 0,
    ) -> tuple[bool, list[RiskViolation]]:
        """
        检查下单请求是否通过风控

        Returns:
            (通过, 违规列表)
        """
        violations: list[RiskViolation] = []

        # === 红线 0: 交易是否已暂停 ===
        if self._trading_paused:
            violations.append(RiskViolation(
                rule="TRADING_PAUSED",
                description=f"交易已暂停: {self._pause_reason}",
            ))
            return False, violations

        # === 红线 1: 单笔金额 ≤ 总资产 20% ===
        order_amount = request.price * request.quantity
        if total_assets > 0:
            ratio = order_amount / total_assets
            if ratio > self.MAX_SINGLE_ORDER_RATIO:
                violations.append(RiskViolation(
                    rule="SINGLE_ORDER_LIMIT",
                    description=f"单笔金额 {order_amount:.0f} 占总资产 {ratio:.1%}，超过 {self.MAX_SINGLE_ORDER_RATIO:.0%} 限制",
                    value=ratio,
                    limit=self.MAX_SINGLE_ORDER_RATIO,
                ))

        # === 红线 2: 日亏损 ≤ 5% ===
        if total_assets > 0 and daily_pnl < 0:
            loss_ratio = abs(daily_pnl) / total_assets
            if loss_ratio >= self.MAX_DAILY_LOSS_RATIO:
                self._trading_paused = True
                self._pause_reason = f"日亏损达 {loss_ratio:.1%}，已自动暂停至次日"
                violations.append(RiskViolation(
                    rule="DAILY_LOSS_LIMIT",
                    description=self._pause_reason,
                    value=loss_ratio,
                    limit=self.MAX_DAILY_LOSS_RATIO,
                ))

        # === 红线 3: 单只股票持仓集中度 ≤ 30% ===
        if request.side == OrderSide.BUY and total_assets > 0:
            existing = current_positions.get(request.ticker, 0.0)
            new_total = existing + order_amount
            concentration = new_total / total_assets
            if concentration > self.MAX_POSITION_CONCENTRATION:
                violations.append(RiskViolation(
                    rule="POSITION_CONCENTRATION",
                    description=f"{request.ticker} 持仓将达 {concentration:.1%}，超过 {self.MAX_POSITION_CONCENTRATION:.0%} 限制",
                    value=concentration,
                    limit=self.MAX_POSITION_CONCENTRATION,
                ))

        # === 红线 4: 下单频率 ≤ 5次/分钟 ===
        now = time.time()
        self._order_timestamps = [t for t in self._order_timestamps if now - t < 60]
        if len(self._order_timestamps) >= self.MAX_ORDERS_PER_MINUTE:
            violations.append(RiskViolation(
                rule="ORDER_FREQUENCY",
                description=f"1分钟内已下单 {len(self._order_timestamps)} 次，超过 {self.MAX_ORDERS_PER_MINUTE} 次限制",
                value=len(self._order_timestamps),
                limit=self.MAX_ORDERS_PER_MINUTE,
            ))

        # === 红线 5: 实盘模式 → 需模拟 ≥ 7天 ===
        if is_live and simulation_days < self.MIN_SIMULATION_DAYS:
            violations.append(RiskViolation(
                rule="SIMULATION_REQUIRED",
                description=f"实盘交易需先模拟运行 ≥ {self.MIN_SIMULATION_DAYS} 天，当前仅 {simulation_days} 天",
                value=simulation_days,
                limit=self.MIN_SIMULATION_DAYS,
            ))

        # 记录时间戳
        if not violations:
            self._order_timestamps.append(now)

        # 记录所有违规
        self._violations.extend(violations)

        passed = len(violations) == 0
        return passed, violations

    def reset_daily(self):
        """每日重置 (收盘后调用)"""
        self._trading_paused = False
        self._pause_reason = ""
        self._daily_loss = 0.0
        self._order_timestamps.clear()

    @property
    def violations_history(self) -> list[RiskViolation]:
        """历史违规记录"""
        return self._violations.copy()

    @property
    def is_paused(self) -> bool:
        return self._trading_paused
