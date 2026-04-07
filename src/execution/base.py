"""
来财 交易执行器基类 — 统一交易接口

所有交易通道 (模拟/同花顺UI/miniQMT) 必须实现此接口。
"""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    FAILED = "failed"


@dataclass
class OrderRequest:
    """下单请求"""
    ticker: str
    side: OrderSide
    price: float
    quantity: int
    market: str = "CN"  # CN / US / HK
    order_type: str = "limit"  # limit / market
    memo: str = ""
    agent_id: str = ""


@dataclass
class OrderResult:
    """下单结果"""
    order_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    status: OrderStatus = OrderStatus.PENDING
    ticker: str = ""
    side: OrderSide = OrderSide.BUY
    price: float = 0.0
    filled_price: float = 0.0
    quantity: int = 0
    filled_quantity: int = 0
    amount: float = 0.0
    commission: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)
    message: str = ""
    channel: str = ""  # simulation / ths_auto / qmt


@dataclass
class Position:
    """持仓"""
    ticker: str
    market: str = "CN"
    quantity: int = 0
    available: int = 0  # 可卖数量 (T+1)
    avg_cost: float = 0.0
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    market_value: float = 0.0


@dataclass
class AccountBalance:
    """账户资金"""
    total_assets: float = 0.0
    available_cash: float = 0.0
    frozen_cash: float = 0.0
    market_value: float = 0.0
    total_pnl: float = 0.0
    daily_pnl: float = 0.0


class BaseBroker(ABC):
    """
    交易执行器基类 — 所有通道必须实现

    通道实现:
    - SimulatorBroker: 模拟交易 (内置撮合)
    - THSBroker: 同花顺 UI 自动化
    - QMTBroker: miniQMT 官方 API
    """

    channel_name: str = "unknown"

    @abstractmethod
    async def connect(self) -> bool:
        """连接交易通道，返回是否成功"""
        ...

    @abstractmethod
    async def disconnect(self):
        """断开连接"""
        ...

    @abstractmethod
    async def buy(self, ticker: str, price: float, quantity: int, **kwargs) -> OrderResult:
        """买入"""
        ...

    @abstractmethod
    async def sell(self, ticker: str, price: float, quantity: int, **kwargs) -> OrderResult:
        """卖出"""
        ...

    @abstractmethod
    async def cancel(self, order_id: str) -> bool:
        """撤单"""
        ...

    @abstractmethod
    async def get_positions(self) -> list[Position]:
        """查询持仓"""
        ...

    @abstractmethod
    async def get_balance(self) -> AccountBalance:
        """查询资金"""
        ...

    @abstractmethod
    async def get_orders(self, date: str | None = None) -> list[OrderResult]:
        """查询委托"""
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """是否已连接"""
        ...

    async def execute_order(self, request: OrderRequest) -> OrderResult:
        """统一下单入口 (自动路由 buy/sell)"""
        if request.side == OrderSide.BUY:
            return await self.buy(request.ticker, request.price, request.quantity)
        else:
            return await self.sell(request.ticker, request.price, request.quantity)
