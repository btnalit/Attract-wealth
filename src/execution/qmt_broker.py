"""
来财 (Attract-wealth) — miniQMT 官方 API 执行器。
"""
from __future__ import annotations

import logging
import random
import time
from typing import Any, Dict, List

from src.execution.base import AccountBalance, BaseBroker, OrderResult, OrderSide, OrderStatus, Position

logger = logging.getLogger(__name__)

try:
    from xtquant.xttrader import XtQuantTrader
    from xtquant.xttype import StockAccount

    XT_AVAILABLE = True
except ImportError:
    XT_AVAILABLE = False


class QMTBroker(BaseBroker):
    """miniQMT 官方 API 执行引擎。"""

    channel_name = "qmt"

    def __init__(self, account_id: str, mini_qmt_path: str = r"D:\国金证券QMT交易端\userdata_mini"):
        self.account_id = account_id
        self.mini_qmt_path = mini_qmt_path
        self._is_connected = False
        self._xt_trader = None
        self._session_id = int(random.randint(100000, 999999))
        self._acc = None
        self._local_order_seq = 0
        self._local_orders: Dict[str, OrderResult] = {}

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    async def connect(self) -> bool:
        if not XT_AVAILABLE:
            raise ImportError("未安装 xtquant，请从券商客户端目录安装 pip install xtquant*.whl")

        logger.info("[%s] 正在连接 miniQMT 客户端 %s ...", self.channel_name, self.mini_qmt_path)
        try:
            self._xt_trader = XtQuantTrader(self.mini_qmt_path, self._session_id)
            self._acc = StockAccount(self.account_id)
            self._xt_trader.start()
            connect_res = self._xt_trader.connect()
            if connect_res != 0:
                logger.error("[%s] connection return non-zero: %s", self.channel_name, connect_res)
                return False
            self._xt_trader.subscribe(self._acc)
            self._is_connected = True
            logger.info("[%s] miniQMT 连接成功，账号: %s", self.channel_name, self.account_id)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("[%s] miniQMT 连接失败: %s", self.channel_name, exc)
            return False

    async def disconnect(self):
        if self._xt_trader:
            self._xt_trader.stop()
        self._is_connected = False
        logger.info("[%s] miniQMT 已断开。", self.channel_name)

    async def buy(self, ticker: str, price: float, quantity: int, **kwargs) -> OrderResult:
        return await self._submit_order(
            ticker=ticker,
            side=OrderSide.BUY,
            price=price,
            quantity=quantity,
        )

    async def sell(self, ticker: str, price: float, quantity: int, **kwargs) -> OrderResult:
        return await self._submit_order(
            ticker=ticker,
            side=OrderSide.SELL,
            price=price,
            quantity=quantity,
        )

    async def cancel(self, order_id: str) -> bool:
        if not self._is_connected or not self._xt_trader:
            return False

        local_order = self._local_orders.get(order_id)
        broker_order_id = _extract_broker_order_id(local_order.message if local_order else "")
        cancel_target = broker_order_id or order_id
        try:
            res = self._xt_trader.cancel_order_stock_async(self._acc, int(cancel_target))
            if res == 0 and local_order:
                local_order.status = OrderStatus.CANCELLED
            return res == 0
        except Exception:
            return False

    async def get_positions(self) -> List[Position]:
        if not self._is_connected or not self._xt_trader:
            return []

        pos_list = self._xt_trader.query_stock_positions(self._acc)
        results = []
        if pos_list:
            for item in pos_list:
                ticker = str(item.stock_code).split(".")[0]
                volume = int(getattr(item, "volume", 0) or 0)
                market_value = float(getattr(item, "market_value", 0.0) or 0.0)
                results.append(
                    Position(
                        ticker=ticker,
                        market="CN",
                        quantity=volume,
                        available=int(getattr(item, "can_use_volume", 0) or 0),
                        avg_cost=float(getattr(item, "open_price", 0.0) or 0.0),
                        current_price=market_value / volume if volume > 0 else 0.0,
                        market_value=market_value,
                    )
                )
        return results

    async def get_balance(self) -> AccountBalance:
        if not self._is_connected or not self._xt_trader:
            return AccountBalance()

        asset = self._xt_trader.query_stock_asset(self._acc)
        if not asset:
            return AccountBalance()
        return AccountBalance(
            total_assets=float(getattr(asset, "total_asset", 0.0) or 0.0),
            available_cash=float(getattr(asset, "cash", 0.0) or 0.0),
            frozen_cash=float(getattr(asset, "frozen_cash", 0.0) or 0.0),
            market_value=float(getattr(asset, "market_value", 0.0) or 0.0),
        )

    async def get_orders(self, date: str | None = None) -> List[OrderResult]:
        local_snapshot = list(self._local_orders.values())
        if not self._is_connected or not self._xt_trader:
            return local_snapshot

        try:
            orders = self._xt_trader.query_stock_orders(self._acc) or []
        except Exception:
            return local_snapshot

        for item in orders:
            mapped = self._map_qmt_order(item)
            local_id = self._extract_local_id_from_order(item) or mapped.order_id

            local = self._local_orders.get(local_id)
            if local:
                local.status = mapped.status
                local.filled_quantity = mapped.filled_quantity
                local.filled_price = mapped.filled_price
                local.message = mapped.message
                local.order_id = local_id
            else:
                mapped.order_id = local_id
                self._local_orders[local_id] = mapped

        return list(self._local_orders.values())

    async def _submit_order(self, ticker: str, side: OrderSide, price: float, quantity: int) -> OrderResult:
        if not self._is_connected or not self._xt_trader:
            raise RuntimeError("miniQMT not connected")

        from xtquant.xttype import xtconstant

        local_id = self._next_local_order_id()
        code = self._format_ticker(ticker)
        order_type = xtconstant.STOCK_BUY if side == OrderSide.BUY else xtconstant.STOCK_SELL
        remark = f"LC:{local_id}"

        broker_id = None
        try:
            if hasattr(self._xt_trader, "order_stock"):
                broker_id = self._xt_trader.order_stock(
                    self._acc,
                    code,
                    order_type,
                    quantity,
                    xtconstant.FIX_PRICE,
                    price,
                    "LaiCai_Auto",
                    remark,
                )
            else:
                broker_id = self._xt_trader.order_stock_async(
                    self._acc,
                    code,
                    order_type,
                    quantity,
                    xtconstant.FIX_PRICE,
                    price,
                    "LaiCai_Auto",
                    remark,
                )
        except Exception as exc:  # noqa: BLE001
            result = OrderResult(
                order_id=local_id,
                status=OrderStatus.FAILED,
                ticker=ticker,
                side=side,
                price=price,
                quantity=quantity,
                channel=self.channel_name,
                message=f"submit_failed:{exc}",
            )
            self._local_orders[local_id] = result
            return result

        broker_id_text = str(broker_id or "")
        result = OrderResult(
            order_id=local_id,
            status=OrderStatus.SUBMITTED,
            ticker=ticker,
            side=side,
            price=price,
            quantity=quantity,
            channel=self.channel_name,
            message=f"broker_order_id={broker_id_text};remark={remark}",
        )
        self._local_orders[local_id] = result
        return result

    def _format_ticker(self, ticker: str) -> str:
        if ticker.startswith("6"):
            return f"{ticker}.SH"
        if ticker.startswith("0") or ticker.startswith("3"):
            return f"{ticker}.SZ"
        if ticker.startswith("8") or ticker.startswith("4"):
            return f"{ticker}.BJ"
        return ticker

    def _next_local_order_id(self) -> str:
        self._local_order_seq += 1
        return f"qmt-{int(time.time() * 1000)}-{self._local_order_seq}"

    def _extract_local_id_from_order(self, order_obj: Any) -> str:
        remark = str(getattr(order_obj, "order_remark", "") or "")
        if "LC:" in remark:
            try:
                return remark.split("LC:", 1)[1].split()[0].strip()
            except Exception:
                return ""
        return ""

    def _map_qmt_order(self, order_obj: Any) -> OrderResult:
        ticker = str(getattr(order_obj, "stock_code", "")).split(".")[0]
        order_volume = int(getattr(order_obj, "order_volume", 0) or 0)
        traded_volume = int(getattr(order_obj, "traded_volume", 0) or 0)
        price = float(getattr(order_obj, "price", 0.0) or 0.0)
        status_code = int(getattr(order_obj, "order_status", -1) or -1)
        side = _map_side(getattr(order_obj, "order_type", None))
        status = _map_qmt_status(status_code=status_code, traded_volume=traded_volume, order_volume=order_volume)
        broker_order_id = str(getattr(order_obj, "order_sysid", "") or getattr(order_obj, "order_id", "") or "")

        return OrderResult(
            order_id=broker_order_id or f"qmt-remote-{int(time.time()*1000)}",
            status=status,
            ticker=ticker,
            side=side,
            price=price,
            filled_price=price if traded_volume > 0 else 0.0,
            quantity=order_volume,
            filled_quantity=traded_volume,
            amount=price * traded_volume if traded_volume > 0 else 0.0,
            channel=self.channel_name,
            message=f"broker_order_id={broker_order_id};status_code={status_code};remark={getattr(order_obj, 'order_remark', '')}",
        )


def _map_side(order_type: Any) -> OrderSide:
    text = str(order_type)
    if text in {"24", "SELL", "stock_sell"}:
        return OrderSide.SELL
    return OrderSide.BUY


def _map_qmt_status(status_code: int, traded_volume: int, order_volume: int) -> OrderStatus:
    # 先按成交量判定
    if order_volume > 0 and traded_volume >= order_volume:
        return OrderStatus.FILLED
    if traded_volume > 0:
        return OrderStatus.PARTIAL

    # 再按状态码兜底（不同券商实现略有差异，采用宽匹配）
    if status_code in {54, 55, 56, 57, 58}:
        return OrderStatus.CANCELLED
    if status_code in {48, 49, 50, 51, 59, 60}:
        return OrderStatus.REJECTED
    if status_code in {0, 1, 2, 3, 4, 5, 11, 12, 13, 14}:
        return OrderStatus.SUBMITTED
    return OrderStatus.PENDING


def _extract_broker_order_id(message: str) -> str:
    text = str(message or "")
    marker = "broker_order_id="
    if marker not in text:
        return ""
    return text.split(marker, 1)[1].split(";", 1)[0].strip()
