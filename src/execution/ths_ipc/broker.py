# -*- coding: utf-8 -*-
"""
THS IPC Broker

通过 TCP Socket 向同花顺内嵌脚本 `laicai_bridge.py` 发送 JSON 指令。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import time
from datetime import datetime
from typing import Any, Dict

from src.execution.base import AccountBalance, BaseBroker, OrderResult, OrderSide, OrderStatus, Position

logger = logging.getLogger(__name__)


class THSIPCBroker(BaseBroker):
    """通过本地 IPC 桥接同花顺交易脚本。"""

    channel_name = "ths_ipc"

    def __init__(self, host: str = "127.0.0.1", port: int = 8089, timeout: float = 3.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.allow_mock = _is_true(os.getenv("THS_IPC_ALLOW_MOCK"), default=False)
        self._connected = False
        self._local_order_seq = 0
        self._local_orders: Dict[str, OrderResult] = {}
        self._runtime: dict[str, Any] = {}

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> bool:
        response = await self._send_request({"action": "ping"})
        runtime = response.get("runtime", {}) if isinstance(response.get("runtime", {}), dict) else {}
        self._runtime = runtime
        ok = response.get("status") == "ok"
        runtime_ready = bool(runtime.get("in_ths_api") or runtime.get("in_xiadan_api"))
        if ok and not runtime_ready and not self.allow_mock:
            self._connected = False
            logger.error(
                "THS IPC 检测到 mock runtime（in_ths_api=%s in_xiadan_api=%s），拒绝连接。"
                "如需调试可设置 THS_IPC_ALLOW_MOCK=true。",
                bool(runtime.get("in_ths_api")),
                bool(runtime.get("in_xiadan_api")),
            )
            return False

        self._connected = ok
        if self._connected:
            logger.info(
                "THS IPC 通道连接成功: %s:%s runtime=%s",
                self.host,
                self.port,
                runtime,
            )
        else:
            logger.error("THS IPC 通道连接失败，请确认同花顺桥接脚本已启动。")
        return self._connected

    async def disconnect(self):
        self._connected = False

    async def buy(self, ticker: str, price: float, quantity: int, **kwargs) -> OrderResult:
        return await self._submit_order(
            ticker=ticker,
            side=OrderSide.BUY,
            price=price,
            quantity=quantity,
            price_mode=kwargs.get("price_mode", price),
        )

    async def sell(self, ticker: str, price: float, quantity: int, **kwargs) -> OrderResult:
        return await self._submit_order(
            ticker=ticker,
            side=OrderSide.SELL,
            price=price,
            quantity=quantity,
            price_mode=kwargs.get("price_mode", price),
        )

    async def cancel(self, order_id: str) -> bool:
        local = self._local_orders.get(order_id)
        broker_order_id = _extract_broker_order_id(local.message if local else "")
        response = await self._send_request(
            {
                "action": "cancel",
                "order_id": broker_order_id or order_id,
                "client_order_id": order_id,
            }
        )
        ok = response.get("status") == "success"
        if ok and local:
            local.status = OrderStatus.CANCELLED
        return ok

    async def get_positions(self) -> list[Position]:
        response = await self._send_request({"action": "get_positions"})
        if response.get("status") != "success":
            return []

        data = response.get("data", {})
        positions: list[Position] = []
        for key, row in _iter_rows(data):
            ticker = _pick_ticker(row, fallback=key)
            if not ticker:
                continue
            quantity = _to_int(row.get("gpye") or row.get("sjsl") or row.get("quantity") or row.get("sz"))
            available = _to_int(row.get("kyye") or row.get("available"))
            avg_cost = _to_float(row.get("cbj") or row.get("cbjg") or row.get("avg_cost") or row.get("cost"))
            market_value = _to_float(row.get("sz") or row.get("zsz") or row.get("market_value"))
            current_price = _to_float(row.get("sj") or row.get("current_price"))
            if current_price <= 0 and market_value > 0 and quantity > 0:
                current_price = market_value / quantity

            positions.append(
                Position(
                    ticker=ticker,
                    market="CN",
                    quantity=quantity,
                    available=available,
                    avg_cost=avg_cost,
                    current_price=current_price,
                    market_value=market_value,
                )
            )
        return positions

    async def get_balance(self) -> AccountBalance:
        response = await self._send_request({"action": "get_balance"})
        if response.get("status") != "success":
            return AccountBalance()

        data = response.get("data", {}) if isinstance(response.get("data", {}), dict) else {}
        available_cash = _to_float(data.get("kyje") or data.get("available_cash") or data.get("cash") or 0.0)
        total_assets = _to_float(data.get("zzc") or data.get("total_assets") or data.get("zjye") or 0.0)
        market_value = _to_float(data.get("zsz") or data.get("sz") or data.get("market_value") or 0.0)
        frozen_cash = _to_float(data.get("djje") or data.get("frozen_cash") or 0.0)
        if total_assets <= 0:
            total_assets = available_cash + market_value + frozen_cash
        if frozen_cash <= 0:
            frozen_cash = max(0.0, total_assets - available_cash - market_value)

        return AccountBalance(
            total_assets=total_assets,
            available_cash=available_cash,
            frozen_cash=frozen_cash,
            market_value=market_value,
        )

    async def get_orders(self, date: str | None = None) -> list[OrderResult]:
        response = await self._send_request(
            {
                "action": "get_orders",
                "mode": "full",
                "include_local_store": True,
            }
        )
        if response.get("status") != "success":
            return list(self._local_orders.values())

        data = response.get("data", [])
        for _, row in _iter_rows(data):
            broker_order_id = str(row.get("order_id") or row.get("htbh") or "").strip()
            client_order_id = str(row.get("client_order_id") or "").strip()
            local_id = client_order_id
            if not local_id and broker_order_id:
                local_id = self._find_local_order_id_by_broker_id(broker_order_id)
            if not local_id:
                local_id = f"ths-remote-{broker_order_id}" if broker_order_id else self._next_local_order_id()

            local = self._local_orders.get(local_id)
            side = _map_side(row.get("side") or row.get("cz"))
            ticker = _pick_ticker(row)
            quantity = _to_int(row.get("quantity") or row.get("wtsl") or 0)
            filled_quantity = _to_int(row.get("filled_quantity") or row.get("cjsl") or 0)
            price = _to_float(row.get("price") or row.get("wtjg") or 0.0)
            filled_price = _to_float(row.get("filled_price") or row.get("cjjj") or 0.0)
            status_raw = str(row.get("status_raw") or row.get("status") or row.get("bz") or "").strip()
            status = _map_ths_status(status_raw)

            if not local:
                local = OrderResult(
                    order_id=local_id,
                    status=status,
                    ticker=ticker,
                    side=side,
                    price=price,
                    quantity=quantity,
                    channel=self.channel_name,
                )
                self._local_orders[local_id] = local

            local.status = status
            local.ticker = local.ticker or ticker
            if local.quantity <= 0 and quantity > 0:
                local.quantity = quantity
            if local.price <= 0 and price > 0:
                local.price = price
            local.filled_quantity = max(local.filled_quantity or 0, filled_quantity)
            if filled_price > 0:
                local.filled_price = filled_price
            local.message = (
                f"broker_order_id={broker_order_id};"
                f"client_order_id={client_order_id};"
                f"status_raw={status_raw};"
                f"status_text={row.get('status_text', '')}"
            )

        return list(self._local_orders.values())

    async def get_trade_snapshot(self) -> dict[str, Any]:
        response = await self._send_request({"action": "get_trade_snapshot"})
        if response.get("status") != "success":
            return {
                "status": "error",
                "message": str(response.get("message", "")),
                "data": {},
                "meta": {},
            }
        return {
            "status": "success",
            "data": response.get("data", {}) if isinstance(response.get("data", {}), dict) else {},
            "meta": response.get("meta", {}) if isinstance(response.get("meta", {}), dict) else {},
        }

    async def _submit_order(
        self,
        *,
        ticker: str,
        side: OrderSide,
        price: float,
        quantity: int,
        price_mode: Any,
    ) -> OrderResult:
        local_id = self._next_local_order_id()
        payload = {
            "action": "buy" if side == OrderSide.BUY else "sell",
            "ticker": ticker,
            "price": price_mode,
            "qty": quantity,
            "client_order_id": local_id,
        }
        response = await self._send_request(payload)
        result = self._parse_order_result(
            response,
            local_order_id=local_id,
            ticker=ticker,
            side=side,
            price=price,
            quantity=quantity,
        )
        self._local_orders[local_id] = result
        return result

    async def _send_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        def _blocking_request() -> Dict[str, Any]:
            try:
                with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
                    message = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                    sock.sendall(message)
                    chunks: list[bytes] = []
                    while True:
                        chunk = sock.recv(4096)
                        if not chunk:
                            break
                        chunks.append(chunk)
                    if not chunks:
                        return {"status": "error", "message": "empty response"}
                    return json.loads(b"".join(chunks).decode("utf-8"))
            except ConnectionRefusedError:
                return {"status": "error", "message": "connection refused"}
            except Exception as exc:  # noqa: BLE001
                return {"status": "error", "message": str(exc)}

        return await asyncio.to_thread(_blocking_request)

    def _parse_order_result(
        self,
        response: Dict[str, Any],
        *,
        local_order_id: str,
        ticker: str,
        side: OrderSide,
        price: float,
        quantity: int,
    ) -> OrderResult:
        ok = response.get("status") == "success"
        trade_result = response.get("trade_result", {})
        broker_order_id = ""
        if isinstance(trade_result, dict):
            broker_order_id = str(trade_result.get("order_id") or trade_result.get("htbh") or "").strip()
        status = OrderStatus.SUBMITTED if ok else OrderStatus.FAILED

        return OrderResult(
            order_id=local_order_id,
            status=status,
            ticker=ticker,
            side=side,
            price=price,
            quantity=quantity,
            timestamp=datetime.now(),
            message=f"broker_order_id={broker_order_id};status_raw={response.get('status', '')}",
            channel=self.channel_name,
        )

    def _next_local_order_id(self) -> str:
        self._local_order_seq += 1
        return f"ths-{int(time.time() * 1000)}-{self._local_order_seq}"

    def _find_local_order_id_by_broker_id(self, broker_order_id: str) -> str:
        if not broker_order_id:
            return ""
        for local_id, order in self._local_orders.items():
            if _extract_broker_order_id(order.message) == broker_order_id:
                return local_id
        return ""


def _map_side(raw: Any) -> OrderSide:
    text = str(raw or "").strip().lower()
    if any(token in text for token in ("sell", "卖", "s")):
        return OrderSide.SELL
    return OrderSide.BUY


def _iter_rows(data: Any) -> list[tuple[str, dict[str, Any]]]:
    rows: list[tuple[str, dict[str, Any]]] = []
    if isinstance(data, list):
        for row in data:
            if isinstance(row, dict):
                rows.append(("", row))
        return rows
    if not isinstance(data, dict):
        return rows

    for key, value in data.items():
        if isinstance(value, dict):
            rows.append((str(key), value))
        elif isinstance(value, list):
            for row in value:
                if isinstance(row, dict):
                    rows.append((str(key), row))
    return rows


def _pick_ticker(row: dict[str, Any], fallback: str = "") -> str:
    ticker = str(row.get("ticker") or row.get("zqdm") or row.get("code") or "").strip()
    if ticker:
        return ticker
    fallback_text = str(fallback or "").strip()
    if fallback_text.isdigit() and len(fallback_text) <= 8:
        return fallback_text
    return ""


def _map_ths_status(raw: Any) -> OrderStatus:
    text = str(raw or "").strip().lower()
    if any(token in text for token in ("filled", "all_traded", "全部成交", "全成", "已成", "dealed")):
        return OrderStatus.FILLED
    if any(token in text for token in ("partial", "part_traded", "部分成交", "部成", "部分撤单", "部撤")):
        return OrderStatus.PARTIAL
    if any(token in text for token in ("cancelled", "canceled", "撤单", "已撤", "废单后撤")):
        return OrderStatus.CANCELLED
    if any(token in text for token in ("rejected", "failed", "拒单", "废单", "error")):
        return OrderStatus.REJECTED
    if any(token in text for token in ("submitted", "pending", "success", "已报", "未成交", "申报", "排队")):
        return OrderStatus.SUBMITTED
    return OrderStatus.PENDING


def _extract_broker_order_id(message: str) -> str:
    text = str(message or "")
    marker = "broker_order_id="
    if marker not in text:
        return ""
    return text.split(marker, 1)[1].split(";", 1)[0].strip()


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _to_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _is_true(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
