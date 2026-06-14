"""
Risk gate for all execution channels.

All orders must pass these hard rules before reaching any broker.

并发安全说明：
- 内部状态（频次窗口、日亏、暂停标志、计数器）使用 threading.Lock 保护，
  确保多线程/多协程并发调用 check_order 时窗口统计与暂停判定一致。
- 注意：check_order 仅保证"单次检查"原子，但"读账户→检查→下单"的整段
  原子性由上层 TradingService 的 asyncio.Lock 保证（见 trading_service.py）。
  两者结合才能彻底封堵 check-then-act 竞态。

白名单（硬红线）：
- 通过 RISK_TICKER_WHITELIST 环境变量注入（逗号分隔，如 "000001,600519,300059"）。
- 未设置时不校验（向后兼容）；一旦设置，非白名单 ticker 一律拒绝，不可被配置绕过。
- 这是真正不可绕过的白名单层（区别于 DirectOrderGuard 的业务层白名单）。

异常处理分级：
- 拒绝路径上的日志发布失败（publish_log）降级为 debug 记录，不阻断风控决策本身。
- 风控核心逻辑（check_order）永不因日志/告警失败而放行订单（fail-safe）。
"""
from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, field
from decimal import Decimal, localcontext
from typing import Any

from src.core.risk_limits import RiskLimits, load_risk_limits
from src.execution.base import OrderRequest, OrderSide

logger = logging.getLogger(__name__)


def _parse_whitelist() -> set[str]:
    """从环境变量解析硬白名单。返回空集合表示不启用白名单校验。"""
    raw = os.getenv("RISK_TICKER_WHITELIST", "").strip()
    if not raw:
        return set()
    return {t.strip() for t in raw.split(",") if t.strip()}


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

    # A 股市场硬规则（中国大陆股票市场通用，不可配置）
    A_SHARE_LOT_SIZE = 100          # 最小交易单位：100 股（1 手）
    A_SHARE_PRICE_TICK = 0.01        # 最小报价变动：0.01 元
    A_SHARE_LIMIT_UP_RATIO = 0.10    # 涨停幅度 10%（主板；ST 5%、创业板/科创板 20% 简化处理）
    A_SHARE_LIMIT_DOWN_RATIO = -0.10  # 跌停幅度 -10%

    def __init__(self, risk_limits: RiskLimits | None = None):
        self._lock = threading.Lock()
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

        # 硬白名单（不可被配置绕过的层）。空集合表示不启用。
        self._ticker_whitelist: set[str] = _parse_whitelist()

        # 软规则参数（可配置，来自 config/risk_limits.toml）。
        # 与硬红线一样在 check_order 中强制执行，区别仅在于参数值可调。
        self.risk_limits: RiskLimits = risk_limits if risk_limits is not None else load_risk_limits()

    def check_order(
        self,
        request: OrderRequest,
        total_assets: float,
        current_positions: dict[str, float],
        daily_pnl: float,
        is_live: bool = False,
        simulation_days: int = 0,
        *,
        position_count: int | None = None,
        total_position_value: float | None = None,
        prev_close: float | None = None,
    ) -> tuple[bool, list[RiskViolation]]:
        # 整段检查 + 状态更新（计数器、频次窗口、暂停标志）必须在同一把锁内完成，
        # 否则并发请求会读到彼此未更新的窗口，绕过频次/暂停红线。
        with self._lock:
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
                return self._finalize_rejection_locked(violations, context)

            # 硬白名单：非空时强制校验，不可被配置绕过。
            if self._ticker_whitelist and request.ticker not in self._ticker_whitelist:
                violations.append(
                    RiskViolation(
                        rule="TICKER_NOT_WHITELISTED",
                        description=(
                            f"标的 {request.ticker} 不在硬白名单中，禁止交易"
                        ),
                        value=0.0,
                        limit=float(len(self._ticker_whitelist)),
                    )
                )

            # 金额计算使用 Decimal，避免 float 累积误差导致 limit 边界误判。
            # 对外 value/limit 仍转回 float 以兼容 JSON 序列化。
            dec_price = Decimal(str(request.price))
            dec_quantity = Decimal(str(request.quantity))
            dec_assets = Decimal(str(total_assets))
            dec_pnl = Decimal(str(daily_pnl))
            order_amount_dec = dec_price * dec_quantity

            if total_assets > 0:
                # 给除法足够精度，避免 DecimalDivisionByZero / 精度不足
                with localcontext() as ctx:
                    ctx.prec = 28
                    ratio_dec = order_amount_dec / dec_assets
                ratio = float(ratio_dec)
                if ratio_dec > Decimal(str(self.MAX_SINGLE_ORDER_RATIO)):
                    violations.append(
                        RiskViolation(
                            rule="SINGLE_ORDER_LIMIT",
                            description=(
                                f"单笔金额 {float(order_amount_dec):.0f} 占总资产 {ratio:.1%}，"
                                f"超过 {self.MAX_SINGLE_ORDER_RATIO:.0%} 限制"
                            ),
                            value=ratio,
                            limit=self.MAX_SINGLE_ORDER_RATIO,
                        )
                    )

            if total_assets > 0 and daily_pnl < 0:
                with localcontext() as ctx:
                    ctx.prec = 28
                    loss_ratio_dec = abs(dec_pnl) / dec_assets
                if loss_ratio_dec >= Decimal(str(self.MAX_DAILY_LOSS_RATIO)):
                    loss_ratio = float(loss_ratio_dec)
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
                existing_dec = Decimal(str(current_positions.get(request.ticker, 0.0)))
                with localcontext() as ctx:
                    ctx.prec = 28
                    concentration_dec = (existing_dec + order_amount_dec) / dec_assets
                if concentration_dec > Decimal(str(self.MAX_POSITION_CONCENTRATION)):
                    violations.append(
                        RiskViolation(
                            rule="POSITION_CONCENTRATION",
                            description=(
                                f"{request.ticker} 持仓将达 {float(concentration_dec):.1%}，"
                                f"超过 {self.MAX_POSITION_CONCENTRATION:.0%} 限制"
                            ),
                            value=float(concentration_dec),
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

            # ===== 软规则（可配置，来自 config/risk_limits.toml）=====
            # 与硬红线一样强制执行，区别仅在于参数值可调。
            self._check_soft_rules(
                violations, context, request, total_assets, current_positions,
                position_count=position_count, total_position_value=total_position_value,
            )

            # A 股市场硬规则（手数、最小变动价位、涨跌停）
            self._check_ashare_rules(violations, context, request, prev_close)

            if violations:
                return self._finalize_rejection_locked(violations, context)

            self._checks_passed += 1
            self._order_timestamps.append(now)
            return True, []

    def _check_soft_rules(
        self,
        violations: list[RiskViolation],
        context: dict[str, Any],
        request: OrderRequest,
        total_assets: float,
        current_positions: dict[str, float],
        *,
        position_count: int | None,
        total_position_value: float | None,
    ) -> None:
        """执行可配置的软规则检查（直接 append 到 violations 列表）。

        注意：调用方必须已持有 self._lock。
        """
        lim = self.risk_limits
        order_amount_dec = Decimal(str(request.price)) * Decimal(str(request.quantity))
        order_amount = float(order_amount_dec)

        # 1. 大额交易预警（预警非阻断：记录告警但不加入 violations，订单仍可放行）
        #    符合 risk_limits.toml 中 large_order_threshold 的"预警"语义。
        if lim.large_order_threshold > 0 and order_amount > lim.large_order_threshold:
            self._append_alert_locked(
                RiskViolation(
                    rule="LARGE_ORDER_ALERT",
                    description=(
                        f"单笔金额 ¥{order_amount:,.0f} 超过大额预警阈值 "
                        f"¥{lim.large_order_threshold:,.0f}（预警，未阻断）"
                    ),
                    value=order_amount,
                    limit=lim.large_order_threshold,
                ),
                context={**context, "severity": "warning", "blocking": False},
            )

        # 以下规则仅对 BUY 有意义（卖出是减仓，不触发上限）
        if request.side != OrderSide.BUY:
            return

        # 2. 总仓位上限
        if lim.max_total_position_ratio > 0 and total_assets > 0:
            current_total = float(total_position_value) if total_position_value is not None else sum(current_positions.values())
            projected_total = current_total + order_amount
            projected_ratio = projected_total / total_assets
            if projected_ratio > lim.max_total_position_ratio:
                violations.append(
                    RiskViolation(
                        rule="TOTAL_POSITION_LIMIT",
                        description=(
                            f"下单后总仓位将达 {projected_ratio:.1%}，"
                            f"超过上限 {lim.max_total_position_ratio:.0%}"
                        ),
                        value=projected_ratio,
                        limit=lim.max_total_position_ratio,
                    )
                )

        # 3. 最大持股数量（仅当买入的是新标的时才计数）
        if lim.max_holding_count > 0 and position_count is not None:
            is_new_position = request.ticker not in current_positions or current_positions.get(request.ticker, 0) <= 0
            projected_count = position_count + (1 if is_new_position else 0)
            if projected_count > lim.max_holding_count:
                violations.append(
                    RiskViolation(
                        rule="HOLDING_COUNT_LIMIT",
                        description=(
                            f"买入后持股数将达 {projected_count}，"
                            f"超过上限 {lim.max_holding_count}"
                        ),
                        value=float(projected_count),
                        limit=float(lim.max_holding_count),
                    )
                )

    def _check_ashare_rules(
        self,
        violations: list[RiskViolation],
        context: dict[str, Any],
        request: OrderRequest,
        prev_close: float | None,
    ) -> None:
        """A 股市场硬规则检查（中国大陆股票市场通用规则）。

        覆盖：
        1. 手数校验：买入数量必须是 100 股（1 手）的整数倍。
           卖出可以是零股（不足 1 手的尾单），但本系统简化为同样要求整手。
        2. 最小报价变动：委托价必须是 0.01 元的整数倍。
        3. 涨跌停校验：委托价不能超过昨收价的 ±10%（需提供 prev_close）。

        注意：调用方必须已持有 self._lock。
        创业板/科创板 20%、ST 5% 的差异化涨跌停暂未区分（简化处理）。
        """
        # 1. 手数校验（仅 CN 市场）
        if getattr(request, "market", "CN") == "CN":
            qty = int(request.quantity)
            if qty <= 0 or qty % self.A_SHARE_LOT_SIZE != 0:
                violations.append(
                    RiskViolation(
                        rule="INVALID_LOT_SIZE",
                        description=(
                            f"A 股委托数量必须为 {self.A_SHARE_LOT_SIZE} 股（1 手）的整数倍，"
                            f"当前 {qty}"
                        ),
                        value=float(qty),
                        limit=float(self.A_SHARE_LOT_SIZE),
                    )
                )

        # 2. 最小报价变动（价格必须是 0.01 的整数倍）
        price = Decimal(str(request.price))
        tick = Decimal(str(self.A_SHARE_PRICE_TICK))
        if price <= 0 or (price % tick) != 0:
            violations.append(
                RiskViolation(
                    rule="INVALID_PRICE_TICK",
                    description=(
                        f"委托价 {request.price} 不符合最小变动价位 "
                        f"¥{self.A_SHARE_PRICE_TICK}（必须为 0.01 的整数倍）"
                    ),
                    value=float(price),
                    limit=float(tick),
                )
            )

        # 3. 涨跌停校验（需要昨收价）
        if prev_close is not None and prev_close > 0:
            prev = Decimal(str(prev_close))
            upper = prev * (Decimal("1") + Decimal(str(self.A_SHARE_LIMIT_UP_RATIO)))
            lower = prev * (Decimal("1") + Decimal(str(self.A_SHARE_LIMIT_DOWN_RATIO)))
            if price > upper:
                violations.append(
                    RiskViolation(
                        rule="PRICE_ABOVE_LIMIT_UP",
                        description=(
                            f"委托价 ¥{float(price):.2f} 超过涨停价 ¥{float(upper):.2f}"
                            f"（昨收 ¥{prev_close:.2f} +{self.A_SHARE_LIMIT_UP_RATIO:.0%}）"
                        ),
                        value=float(price),
                        limit=float(upper),
                    )
                )
            elif price < lower:
                violations.append(
                    RiskViolation(
                        rule="PRICE_BELOW_LIMIT_DOWN",
                        description=(
                            f"委托价 ¥{float(price):.2f} 低于跌停价 ¥{float(lower):.2f}"
                            f"（昨收 ¥{prev_close:.2f} {self.A_SHARE_LIMIT_DOWN_RATIO:.0%}）"
                        ),
                        value=float(price),
                        limit=float(lower),
                    )
                )

    def _finalize_rejection_locked(
        self,
        violations: list[RiskViolation],
        context: dict[str, Any],
    ) -> tuple[bool, list[RiskViolation]]:
        """拒绝收尾（调用方已持有 _lock，不再重复加锁）。

        异常分级：日志/告警发布的失败降级为 debug 记录，绝不影响拒绝决策本身（fail-safe）。
        """
        self._checks_rejected += 1
        self._violations.extend(violations)
        for violation in violations:
            self._rule_hits[violation.rule] += 1
            self._append_alert_locked(violation, context=context)
            try:
                from src.routers.stream import publish_log
                publish_log("RISK", f"Risk Violation: {violation.rule} - {violation.description}", level="error")
            except Exception as exc:  # noqa: BLE001
                # 日志发布失败不影响风控决策；降级记录，便于排查 stream 通道问题。
                logger.debug("risk alert publish failed (non-fatal): %s", exc)
        return False, violations

    def check_positions(
        self,
        positions: list[dict[str, Any]],
    ) -> list[RiskViolation]:
        """检查已有持仓的止损/止盈触发。

        参数 positions: 每个元素是 dict，需含 ticker / avg_cost / current_price / market_value。
        返回触发的止损止盈违规列表（空列表表示无触发）。

        注意：本方法返回的是"建议性"违规（应卖出），不阻断当前 check_order 流程。
        调用方（TradingService / EventEngine）负责据此生成卖出信号。
        """
        lim = self.risk_limits
        triggered: list[RiskViolation] = []
        with self._lock:
            for pos in positions:
                ticker = str(pos.get("ticker", ""))
                avg_cost = float(pos.get("avg_cost") or 0.0)
                current_price = float(pos.get("current_price") or 0.0)
                if avg_cost <= 0 or current_price <= 0:
                    continue
                from decimal import Decimal as _D
                pnl_ratio = (_D(str(current_price)) - _D(str(avg_cost))) / _D(str(avg_cost))
                pnl_ratio_f = float(pnl_ratio)

                # 止损
                if lim.stop_loss_percent < 0 and pnl_ratio <= lim.stop_loss_percent:
                    triggered.append(
                        RiskViolation(
                            rule="STOP_LOSS_TRIGGERED",
                            description=(
                                f"{ticker} 亏损 {pnl_ratio_f:.1%}，触及止损线 {lim.stop_loss_percent:.1%}，"
                                f"建议立即卖出"
                            ),
                            value=pnl_ratio_f,
                            limit=lim.stop_loss_percent,
                        )
                    )
                # 止盈
                elif lim.take_profit_percent > 0 and pnl_ratio >= lim.take_profit_percent:
                    triggered.append(
                        RiskViolation(
                            rule="TAKE_PROFIT_TRIGGERED",
                            description=(
                                f"{ticker} 盈利 {pnl_ratio_f:.1%}，触及止盈线 {lim.take_profit_percent:.1%}，"
                                f"建议获利了结"
                            ),
                            value=pnl_ratio_f,
                            limit=lim.take_profit_percent,
                        )
                    )
        return triggered

    def _append_alert_locked(self, violation: RiskViolation, context: dict[str, Any]):
        """追加告警（调用方已持有 _lock）。"""
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
        with self._lock:
            self._trading_paused = False
            self._pause_reason = ""
            self._daily_loss = 0.0
            self._order_timestamps.clear()

    def get_recent_alerts(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            n = max(1, int(limit))
            return [asdict(alert) for alert in self._alerts[-n:]][::-1]

    def get_metrics(self) -> dict[str, Any]:
        with self._lock:
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
        with self._lock:
            return self._violations.copy()

    @property
    def is_paused(self) -> bool:
        with self._lock:
            return self._trading_paused
