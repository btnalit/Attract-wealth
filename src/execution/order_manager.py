"""
来财 (Attract-wealth) — 订单状态管理器。

职责：
- 跟踪活跃订单
- 同步 broker 订单状态
- 幂等更新 ledger
- 提供日切钩子
"""
from __future__ import annotations

import asyncio
import logging
from typing import Dict

from src.core.trading_ledger import TradingLedger
from src.execution.base import BaseBroker, OrderResult, OrderStatus

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = {OrderStatus.PENDING, OrderStatus.SUBMITTED, OrderStatus.PARTIAL}
TERMINAL_STATUSES = {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.FAILED}


class OrderManager:
    """订单生命周期及状态同步管理器。"""

    def __init__(self, broker: BaseBroker):
        self.broker = broker
        self.active_orders: Dict[str, OrderResult] = {}
        self._last_signatures: Dict[str, str] = {}
        self._broker_order_refs: Dict[str, str] = {}
        self._is_syncing = False

    def add_active_order(self, order: OrderResult) -> None:
        """登记一个新的活跃订单进入轮询。"""
        if not order.order_id:
            return
        if order.status in ACTIVE_STATUSES:
            self.active_orders[order.order_id] = order
            self._last_signatures[order.order_id] = self._signature(order)
            broker_order_id = self._extract_broker_order_id(order.message)
            if broker_order_id:
                self._broker_order_refs[order.order_id] = broker_order_id
            logger.info("登记活跃订单: %s [%s %s]", order.order_id, order.ticker, order.side.value)

    async def sync_now(self) -> dict[str, int]:
        """执行一次同步并返回统计。"""
        return await self._sync_once()

    async def _sync_once(self) -> dict[str, int]:
        stats = {"seen": 0, "updated": 0, "removed": 0, "idempotent": 0}
        if not self.active_orders:
            return stats
        if not self.broker.is_connected:
            return stats

        try:
            broker_orders = await self.broker.get_orders()
            broker_map = {item.order_id: item for item in broker_orders if item.order_id}
            broker_order_ref_map: Dict[str, OrderResult] = {}
            for item in broker_orders:
                for ref in self._collect_broker_refs(item):
                    broker_order_ref_map.setdefault(ref, item)

            to_remove: list[str] = []
            for order_id, local_order in list(self.active_orders.items()):
                stats["seen"] += 1
                remote = broker_map.get(order_id)
                if not remote:
                    broker_ref = self._resolve_local_broker_ref(order_id, local_order)
                    if broker_ref:
                        remote = broker_order_ref_map.get(broker_ref)
                if not remote:
                    continue

                if remote.order_id and remote.order_id != order_id:
                    self._broker_order_refs[order_id] = remote.order_id
                remote_broker_id = self._extract_broker_order_id(remote.message)
                if remote_broker_id:
                    self._broker_order_refs[order_id] = remote_broker_id

                signature = self._signature(remote)
                if self._last_signatures.get(order_id) == signature:
                    stats["idempotent"] += 1
                    if remote.status in TERMINAL_STATUSES:
                        to_remove.append(order_id)
                    continue

                self._last_signatures[order_id] = signature
                local_order.status = remote.status
                local_order.filled_quantity = remote.filled_quantity
                local_order.filled_price = remote.filled_price

                result = TradingLedger.update_trade_status(
                    trade_id=order_id,
                    status=remote.status,
                    filled_price=remote.filled_price,
                    filled_quantity=remote.filled_quantity,
                )
                if result.get("updated"):
                    stats["updated"] += 1
                    logger.info(
                        "订单状态更新: order_id=%s status=%s filled=%s",
                        order_id,
                        result.get("status"),
                        remote.filled_quantity,
                    )
                else:
                    stats["idempotent"] += 1

                if remote.status in TERMINAL_STATUSES:
                    to_remove.append(order_id)

            for oid in to_remove:
                self.active_orders.pop(oid, None)
                self._last_signatures.pop(oid, None)
                self._broker_order_refs.pop(oid, None)
                stats["removed"] += 1
        except Exception as exc:  # noqa: BLE001
            logger.error("订单状态同步失败: %s", exc, exc_info=True)
        return stats

    async def start_sync_loop(self, interval: float = 3.0):
        """启动后台同步轮询。"""
        self._is_syncing = True
        logger.info("启动订单同步轮询任务，通道: %s", self.broker.channel_name)
        while self._is_syncing:
            await self._sync_once()
            await asyncio.sleep(interval)

    def stop_sync_loop(self):
        self._is_syncing = False

    def on_day_roll(self):
        """
        交易日切换钩子。

        保留活跃订单（可能隔夜未回报），但会清理签名缓存以强制次日重新对账。
        """
        self._last_signatures.clear()

    @staticmethod
    def _signature(order: OrderResult) -> str:
        status = order.status.value if hasattr(order.status, "value") else str(order.status)
        return f"{status}|{order.filled_quantity}|{round(float(order.filled_price or 0.0), 6)}"

    def _resolve_local_broker_ref(self, local_order_id: str, order: OrderResult) -> str:
        ref = self._broker_order_refs.get(local_order_id, "")
        if ref:
            return ref
        ref = self._extract_broker_order_id(order.message)
        if ref:
            self._broker_order_refs[local_order_id] = ref
        return ref

    @staticmethod
    def _collect_broker_refs(order: OrderResult) -> list[str]:
        refs: list[str] = []
        if order.order_id:
            refs.append(order.order_id)
        from_message = OrderManager._extract_broker_order_id(order.message)
        if from_message and from_message not in refs:
            refs.append(from_message)
        return refs

    @staticmethod
    def _extract_broker_order_id(message: str) -> str:
        marker = "broker_order_id="
        text = str(message or "")
        if marker not in text:
            return ""
        return text.split(marker, 1)[1].split(";", 1)[0].strip()
