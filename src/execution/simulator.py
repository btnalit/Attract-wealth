"""
来财 模拟交易引擎 — 零风险策略验证

内置撮合逻辑、滑点模拟、手续费计算。
与真实交易通道共享相同的 BaseBroker 接口。
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from src.execution.base import (
    AccountBalance,
    BaseBroker,
    OrderResult,
    OrderSide,
    OrderStatus,
    Position,
)


class SimulatorBroker(BaseBroker):
    """模拟交易引擎"""

    channel_name = "simulation"

    # 手续费率
    COMMISSION_RATE = 0.0003   # 万三
    MIN_COMMISSION = 5.0       # 最低 5 元
    STAMP_TAX_RATE = 0.0005    # 印花税 万五 (仅卖出)
    SLIPPAGE_BPS = 2           # 滑点 2 个基点

    def __init__(self, initial_balance: float = 1_000_000.0):
        self._balance = initial_balance
        self._initial_balance = initial_balance
        self._positions: dict[str, Position] = {}
        self._orders: list[OrderResult] = []
        self._connected = False

    async def connect(self) -> bool:
        self._connected = True
        return True

    async def disconnect(self):
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def buy(self, ticker: str, price: float, quantity: int, **kwargs) -> OrderResult:
        """模拟买入"""
        # 模拟滑点 (买入价略高)
        fill_price = price * (1 + self.SLIPPAGE_BPS / 10000)
        amount = fill_price * quantity

        # 手续费
        commission = max(amount * self.COMMISSION_RATE, self.MIN_COMMISSION)
        total_cost = amount + commission

        # 资金检查
        if total_cost > self._balance:
            result = OrderResult(
                status=OrderStatus.REJECTED,
                ticker=ticker,
                side=OrderSide.BUY,
                price=price,
                quantity=quantity,
                message=f"资金不足: 需要 {total_cost:.2f}, 可用 {self._balance:.2f}",
                channel=self.channel_name,
            )
            self._orders.append(result)
            return result

        # 扣款
        self._balance -= total_cost

        # 更新持仓
        if ticker in self._positions:
            pos = self._positions[ticker]
            total_qty = pos.quantity + quantity
            pos.avg_cost = (pos.avg_cost * pos.quantity + fill_price * quantity) / total_qty
            pos.quantity = total_qty
            pos.market_value = pos.quantity * fill_price
        else:
            self._positions[ticker] = Position(
                ticker=ticker,
                quantity=quantity,
                available=0,  # T+1, 当日不可卖
                avg_cost=fill_price,
                current_price=fill_price,
                market_value=quantity * fill_price,
            )

        result = OrderResult(
            order_id=str(uuid.uuid4())[:12],
            status=OrderStatus.FILLED,
            ticker=ticker,
            side=OrderSide.BUY,
            price=price,
            filled_price=fill_price,
            quantity=quantity,
            filled_quantity=quantity,
            amount=amount,
            commission=commission,
            channel=self.channel_name,
        )
        self._orders.append(result)
        return result

    async def sell(self, ticker: str, price: float, quantity: int, **kwargs) -> OrderResult:
        """模拟卖出"""
        pos = self._positions.get(ticker)
        if not pos or pos.available < quantity:
            avail = pos.available if pos else 0
            result = OrderResult(
                status=OrderStatus.REJECTED,
                ticker=ticker,
                side=OrderSide.SELL,
                price=price,
                quantity=quantity,
                message=f"可卖不足: 需要 {quantity}, 可卖 {avail}",
                channel=self.channel_name,
            )
            self._orders.append(result)
            return result

        # 模拟滑点 (卖出价略低)
        fill_price = price * (1 - self.SLIPPAGE_BPS / 10000)
        amount = fill_price * quantity

        # 手续费 + 印花税
        commission = max(amount * self.COMMISSION_RATE, self.MIN_COMMISSION)
        stamp_tax = amount * self.STAMP_TAX_RATE
        net_amount = amount - commission - stamp_tax

        # 入账
        self._balance += net_amount

        # 更新持仓
        pos.quantity -= quantity
        pos.available -= quantity
        if pos.quantity <= 0:
            del self._positions[ticker]
        else:
            pos.market_value = pos.quantity * fill_price

        # 计算盈亏
        pnl = (fill_price - pos.avg_cost) * quantity - commission - stamp_tax

        result = OrderResult(
            order_id=str(uuid.uuid4())[:12],
            status=OrderStatus.FILLED,
            ticker=ticker,
            side=OrderSide.SELL,
            price=price,
            filled_price=fill_price,
            quantity=quantity,
            filled_quantity=quantity,
            amount=amount,
            commission=commission + stamp_tax,
            channel=self.channel_name,
            message=f"盈亏: {pnl:+.2f}",
        )
        self._orders.append(result)
        return result

    async def cancel(self, order_id: str) -> bool:
        return False  # 模拟引擎立即成交，无法撤单

    async def get_positions(self) -> list[Position]:
        return list(self._positions.values())

    async def get_balance(self) -> AccountBalance:
        market_value = sum(p.market_value for p in self._positions.values())
        total = self._balance + market_value
        return AccountBalance(
            total_assets=total,
            available_cash=self._balance,
            frozen_cash=0.0,
            market_value=market_value,
            total_pnl=total - self._initial_balance,
        )

    async def get_orders(self, date: str | None = None) -> list[OrderResult]:
        if date:
            target = datetime.strptime(date, "%Y-%m-%d").date()
            return [o for o in self._orders if o.timestamp.date() == target]
        return self._orders.copy()

    async def get_trade_snapshot(self) -> dict[str, Any]:
        balance = await self.get_balance()
        positions = await self.get_positions()
        orders = await self.get_orders()
        return {
            "balance": balance,
            "positions": positions,
            "orders": orders,
            "meta": {
                "channel": self.channel_name,
                "orders_count": len(orders),
                "positions_count": len(positions),
            },
        }

    def new_day(self):
        """模拟新交易日 — T+1可卖"""
        for pos in self._positions.values():
            pos.available = pos.quantity
