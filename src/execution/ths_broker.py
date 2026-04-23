"""
THS client broker powered by easytrader.

This channel is the fallback path when ths_ipc host bridge is unavailable.
It assumes `xiadan.exe` is already logged in and accessible in current Windows session.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import win32gui
from pywinauto import Desktop

from src.core.ths_host_autostart import read_ths_account_context
from src.execution.base import AccountBalance, BaseBroker, OrderResult, OrderSide, OrderStatus, Position
from src.execution.ths_auto.easytrader_adapter import (
    compact_probe_for_log,
    create_easytrader_client,
    extract_account_fields,
    extract_broker_order_id,
    normalize_balance,
    normalize_orders,
    normalize_positions,
    normalize_trades,
)

logger = logging.getLogger(__name__)


class THSBroker(BaseBroker):
    """THS auto broker using easytrader."""

    channel_name = "ths_auto"

    def __init__(self, exe_path: str | None = None):
        # Phase 6: 自适应 THS 路径探测 (T-32)
        from src.core.ths_path_resolver import resolve_ths_path

        if exe_path:
            self.exe_path = exe_path
        else:
            ths_info = resolve_ths_path()
            self.exe_path = ths_info.get("exe_path") or r"C:\同花顺软件\同花顺\xiadan.exe"
            if ths_info.get("found"):
                logger.info("THS 路径自动探测成功: %s (source=%s)", ths_info["install_dir"], ths_info["source"])
            else:
                logger.warning("THS 路径自动探测失败，使用默认路径: %s", self.exe_path)
        self.easytrader_repo = os.getenv("EASYTRADER_REPO_PATH", "").strip()
        self.easytrader_broker = os.getenv("THS_EASYTRADER_BROKER", "ths").strip() or "ths"
        self.easytrader_grid_strategy = os.getenv("THS_EASYTRADER_GRID_STRATEGY", "auto").strip() or "auto"
        self.easytrader_captcha_engine = os.getenv("THS_EASYTRADER_CAPTCHA_ENGINE", "auto").strip() or "auto"
        self._is_connected = False
        self._client: Any = None
        self._connect_meta: dict[str, Any] = {}
        self.hwnd: int | None = None
        self.window_title: str = ""
        self._local_order_seq = 0
        self._local_orders: dict[str, OrderResult] = {}
        self.submit_max_attempts = max(1, _safe_int(os.getenv("THS_AUTO_SUBMIT_MAX_ATTEMPTS"), 2))
        self.submit_retry_interval_s = max(0.0, _safe_float(os.getenv("THS_AUTO_SUBMIT_RETRY_INTERVAL_S"), 0.35))
        self.submit_retry_backoff = max(1.0, _safe_float(os.getenv("THS_AUTO_SUBMIT_RETRY_BACKOFF"), 1.6))
        self.rebind_hwnd_on_submit = _is_true(os.getenv("THS_AUTO_REBIND_HWND_ON_SUBMIT"), default=True)
        self.strict_hwnd_health = _is_true(os.getenv("THS_AUTO_STRICT_HWND_HEALTH"), default=False)
        transient_tokens = os.getenv("THS_AUTO_SUBMIT_TRANSIENT_TOKENS", "").strip()
        self.submit_transient_tokens = tuple(
            token.strip().lower()
            for token in (transient_tokens.split(",") if transient_tokens else _DEFAULT_TRANSIENT_SUBMIT_TOKENS)
            if token.strip()
        )

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    def check_health(self) -> dict:
        """检查同花顺下单窗口存活状态 (HWND 校验)"""
        is_alive = win32gui.IsWindow(self.hwnd) if self.hwnd else False
        is_visible = bool(is_alive and win32gui.IsWindowVisible(self.hwnd))
        foreground_hwnd = 0
        is_foreground = False
        if is_alive:
            try:
                foreground_hwnd = int(win32gui.GetForegroundWindow() or 0)
                is_foreground = bool(foreground_hwnd and foreground_hwnd == int(self.hwnd))
            except Exception:  # noqa: BLE001
                foreground_hwnd = 0
                is_foreground = False
        return {
            "hwnd": self.hwnd,
            "title": self.window_title,
            "status": "active" if is_alive else "dead",
            "visible": is_visible,
            "foreground": is_foreground,
            "foreground_hwnd": foreground_hwnd,
            "is_connected": self.is_connected and is_alive,
        }

    async def connect(self) -> bool:
        """Connect to logged THS client via easytrader."""
        client, meta = await asyncio.to_thread(
            create_easytrader_client,
            exe_path=self.exe_path,
            broker=self.easytrader_broker,
            repo_path=self.easytrader_repo,
            grid_strategy=self.easytrader_grid_strategy,
            captcha_engine=self.easytrader_captcha_engine,
        )

        # 查找同花顺下单窗口 (HWND 绑定)
        self._rebind_hwnd(log_prefix="connect")

        self._connect_meta = meta
        self._client = client
        self._is_connected = client is not None
        if self._is_connected:
            logger.info(
                "[%s] easytrader connected. meta=%s",
                self.channel_name,
                compact_probe_for_log({"ok": True, "connected": True, "meta": meta, "summary": {}, "errors": []}),
            )
            return True

        allow_stub = _is_true(os.getenv("THS_AUTO_ALLOW_STUB"), default=False)
        logger.error(
            "[%s] easytrader connect failed (allow_stub=%s): %s",
            self.channel_name,
            allow_stub,
            meta,
        )
        if allow_stub:
            self._is_connected = True
            logger.warning("[%s] running in stub mode due to THS_AUTO_ALLOW_STUB=true", self.channel_name)
            return True
        return False

    async def disconnect(self):
        client = self._client
        self._client = None
        self._is_connected = False
        if client is None:
            return

        close_on_disconnect = _is_true(os.getenv("THS_AUTO_CLOSE_ON_DISCONNECT"), default=False)
        if not close_on_disconnect:
            logger.info(
                "[%s] disconnected without closing THS client (THS_AUTO_CLOSE_ON_DISCONNECT=false)",
                self.channel_name,
            )
            return

        exit_fn = getattr(client, "exit", None)
        if callable(exit_fn):
            try:
                await asyncio.to_thread(exit_fn)
            except Exception:  # noqa: BLE001
                pass

    async def buy(self, ticker: str, price: float, quantity: int, **kwargs) -> OrderResult:
        return await self._submit_order(ticker=ticker, side=OrderSide.BUY, price=price, quantity=quantity)

    async def sell(self, ticker: str, price: float, quantity: int, **kwargs) -> OrderResult:
        return await self._submit_order(ticker=ticker, side=OrderSide.SELL, price=price, quantity=quantity)

    async def cancel(self, order_id: str) -> bool:
        if not self._is_connected:
            return False
        client = self._client
        if client is None:
            return _is_true(os.getenv("THS_AUTO_ALLOW_STUB"), default=False)

        cancel_fn = getattr(client, "cancel_entrust", None)
        if not callable(cancel_fn):
            logger.error("[%s] easytrader client missing cancel_entrust", self.channel_name)
            return False

        local = self._local_orders.get(order_id)
        broker_order_id = _extract_local_broker_order_id(local.message if local else "") or order_id
        try:
            raw = await asyncio.to_thread(cancel_fn, broker_order_id)
        except Exception as exc:  # noqa: BLE001
            logger.error("[%s] cancel failed: %s", self.channel_name, exc)
            return False

        ok = _cancel_result_ok(raw)
        if ok and local is not None:
            local.status = OrderStatus.CANCELLED
        return ok

    async def get_positions(self) -> list[Position]:
        if not self._is_connected:
            return []
        client = self._client
        if client is None:
            return []

        try:
            raw = await asyncio.to_thread(lambda: getattr(client, "position"))
        except Exception as exc:  # noqa: BLE001
            logger.error("[%s] read positions failed: %s", self.channel_name, exc)
            return []

        rows = normalize_positions(raw)
        return [
            Position(
                ticker=row["ticker"],
                market="CN",
                quantity=int(row["quantity"]),
                available=int(row["available"]),
                avg_cost=float(row["avg_cost"]),
                current_price=float(row["current_price"]),
                market_value=float(row["market_value"]),
            )
            for row in rows
        ]

    async def get_balance(self) -> AccountBalance:
        if not self._is_connected:
            return AccountBalance()
        client = self._client
        if client is None:
            return AccountBalance()

        try:
            raw = await asyncio.to_thread(lambda: getattr(client, "balance"))
        except Exception as exc:  # noqa: BLE001
            logger.error("[%s] read balance failed: %s", self.channel_name, exc)
            return AccountBalance()

        row = normalize_balance(raw)
        return AccountBalance(
            total_assets=float(row["total_assets"]),
            available_cash=float(row["available_cash"]),
            frozen_cash=float(row["frozen_cash"]),
            market_value=float(row["market_value"]),
        )

    async def get_orders(self, date: str | None = None) -> list[OrderResult]:
        local_snapshot = list(self._local_orders.values())
        if not self._is_connected:
            return local_snapshot
        client = self._client
        if client is None:
            return local_snapshot

        try:
            raw = await asyncio.to_thread(lambda: getattr(client, "today_entrusts"))
        except Exception as exc:  # noqa: BLE001
            logger.error("[%s] read today_entrusts failed: %s", self.channel_name, exc)
            return local_snapshot

        remote_rows = normalize_orders(raw)
        for row in remote_rows:
            broker_id = str(row.get("order_id", "")).strip()
            local_id = self._find_local_order_id_by_broker_id(broker_id)
            if not local_id:
                local_id = f"ths-auto-remote-{broker_id}" if broker_id else self._next_local_order_id()

            side = OrderSide.BUY if str(row.get("side", "BUY")).upper() != "SELL" else OrderSide.SELL
            status = _map_status(str(row.get("status", "")))
            item = self._local_orders.get(local_id)
            if item is None:
                item = OrderResult(
                    order_id=local_id,
                    status=status,
                    ticker=str(row.get("ticker", "")),
                    side=side,
                    price=float(row.get("price", 0.0)),
                    quantity=int(row.get("quantity", 0)),
                    channel=self.channel_name,
                )
                self._local_orders[local_id] = item

            item.status = status
            item.ticker = item.ticker or str(row.get("ticker", ""))
            if item.price <= 0:
                item.price = float(row.get("price", 0.0))
            if item.quantity <= 0:
                item.quantity = int(row.get("quantity", 0))
            item.filled_quantity = max(item.filled_quantity, int(row.get("filled_quantity", 0)))
            filled_price = float(row.get("filled_price", 0.0))
            if filled_price > 0:
                item.filled_price = filled_price
            item.message = (
                f"broker_order_id={broker_id};status_raw={row.get('status_raw', '')};"
                f"source=easytrader"
            )
        return list(self._local_orders.values())

    async def get_trade_snapshot(self) -> dict[str, Any]:
        if not self._is_connected:
            return {"status": "error", "message": "broker not connected", "data": {}, "meta": {}}
        client = self._client
        if client is None:
            return {"status": "error", "message": "easytrader client unavailable", "data": {}, "meta": {}}

        try:
            raw_balance = await asyncio.to_thread(lambda: getattr(client, "balance"))
            raw_positions = await asyncio.to_thread(lambda: getattr(client, "position"))
            raw_orders = await asyncio.to_thread(lambda: getattr(client, "today_entrusts"))
            raw_trades = await asyncio.to_thread(lambda: getattr(client, "today_trades"))
        except Exception as exc:  # noqa: BLE001
            return {
                "status": "error",
                "message": f"snapshot read failed: {exc}",
                "data": {},
                "meta": {"channel": self.channel_name},
            }

        normalized_balance = normalize_balance(raw_balance)
        normalized_positions = normalize_positions(raw_positions)
        normalized_orders = normalize_orders(raw_orders)
        normalized_trades = normalize_trades(raw_trades)
        account_fields = extract_account_fields(raw_balance)
        ths_root = Path(os.getenv("THS_ROOT_PATH", r"D:\同花顺软件\同花顺")).expanduser()
        account_context = read_ths_account_context(ths_root)
        if not account_fields.get("account_id"):
            fallback_account = str(account_context.get("last_user_name", "") or account_context.get("ai_user_account", "")).strip()
            if fallback_account:
                account_fields["account_id"] = fallback_account

        return {
            "status": "success",
            "data": {
                "account": account_fields,
                "account_context": account_context,
                "balance": raw_balance if isinstance(raw_balance, dict) else {},
                "positions": raw_positions,
                "orders": raw_orders,
                "trades": raw_trades,
                "normalized": {
                    "balance": normalized_balance,
                    "positions": normalized_positions,
                    "orders": normalized_orders,
                    "trades": normalized_trades,
                    "summary": {
                        "has_balance": bool(
                            float(normalized_balance.get("available_cash", 0.0) or 0.0) > 0
                            or float(normalized_balance.get("total_assets", 0.0) or 0.0) > 0
                        ),
                        "positions_count": len(normalized_positions),
                        "orders_count": len(normalized_orders),
                        "trades_count": len(normalized_trades),
                        "available_cash": float(normalized_balance.get("available_cash", 0.0) or 0.0),
                        "total_assets": float(normalized_balance.get("total_assets", 0.0) or 0.0),
                        "market_value": float(normalized_balance.get("market_value", 0.0) or 0.0),
                        "account_id": str(account_fields.get("account_id", "") or ""),
                    },
                },
            },
            "meta": {
                "channel": self.channel_name,
                "connect_meta": self._connect_meta,
            },
        }

    async def _submit_order(
        self,
        *,
        ticker: str,
        side: OrderSide,
        price: float,
        quantity: int,
    ) -> OrderResult:
        local_id = self._next_local_order_id()
        if not self._is_connected:
            return OrderResult(
                order_id=local_id,
                status=OrderStatus.FAILED,
                ticker=ticker,
                side=side,
                price=price,
                quantity=quantity,
                channel=self.channel_name,
                message="broker not connected",
            )

        if self._client is None:
            # Explicitly keep previous stub behavior for environments without easytrader.
            if _is_true(os.getenv("THS_AUTO_ALLOW_STUB"), default=False):
                result = OrderResult(
                    order_id=local_id,
                    status=OrderStatus.SUBMITTED,
                    ticker=ticker,
                    side=side,
                    price=price,
                    quantity=quantity,
                    channel=self.channel_name,
                    message="stub_order_submitted",
                )
                self._local_orders[local_id] = result
                return result
            return OrderResult(
                order_id=local_id,
                status=OrderStatus.FAILED,
                ticker=ticker,
                side=side,
                price=price,
                quantity=quantity,
                channel=self.channel_name,
                message="easytrader client unavailable",
            )

        trade_fn = getattr(self._client, "buy" if side == OrderSide.BUY else "sell", None)
        if not callable(trade_fn):
            result = OrderResult(
                order_id=local_id,
                status=OrderStatus.FAILED,
                ticker=ticker,
                side=side,
                price=price,
                quantity=quantity,
                channel=self.channel_name,
                message="easytrader missing buy/sell API",
            )
            self._local_orders[local_id] = result
            return result

        health_before = self.check_health()
        rebound = False
        if self.rebind_hwnd_on_submit and health_before.get("status") != "active":
            rebound = self._rebind_hwnd(log_prefix="submit_precheck")
        health_after = self.check_health()
        if self.strict_hwnd_health and health_after.get("status") != "active":
            result = OrderResult(
                order_id=local_id,
                status=OrderStatus.FAILED,
                ticker=ticker,
                side=side,
                price=price,
                quantity=quantity,
                channel=self.channel_name,
                message=(
                    "submit_blocked_by_hwnd_health;"
                    f"diag={_compact_json({'before': health_before, 'after': health_after, 'rebound': rebound})}"
                ),
            )
            self._local_orders[local_id] = result
            return result

        attempts = max(1, int(self.submit_max_attempts))
        sleep_seconds = float(self.submit_retry_interval_s)
        backoff = float(self.submit_retry_backoff)
        errors: list[dict[str, Any]] = []
        result: OrderResult | None = None

        for attempt in range(1, attempts + 1):
            try:
                raw = await asyncio.to_thread(trade_fn, ticker, price, quantity)
                broker_order_id = extract_broker_order_id(raw)
                diag = {
                    "attempt": attempt,
                    "attempts": attempts,
                    "hwnd_health_before": health_before,
                    "hwnd_health_after": health_after,
                    "hwnd_rebound": rebound,
                    "errors": errors,
                }
                result = OrderResult(
                    order_id=local_id,
                    status=OrderStatus.SUBMITTED,
                    ticker=ticker,
                    side=side,
                    price=price,
                    quantity=quantity,
                    channel=self.channel_name,
                    message=(
                        f"broker_order_id={broker_order_id};"
                        "source=easytrader;"
                        f"diag={_compact_json(diag)};"
                        f"raw={_safe_compact(raw)}"
                    ),
                )
                break
            except Exception as exc:  # noqa: BLE001
                err_text = str(exc)
                transient = _is_transient_submit_error(err_text, self.submit_transient_tokens)
                errors.append({"attempt": attempt, "transient": transient, "error": _truncate_text(err_text, 240)})
                should_retry = transient and attempt < attempts
                if should_retry:
                    if self.rebind_hwnd_on_submit:
                        self._rebind_hwnd(log_prefix=f"submit_retry_{attempt}")
                    if sleep_seconds > 0:
                        await asyncio.sleep(sleep_seconds * (backoff ** (attempt - 1)))
                    continue
                diag = {
                    "attempt": attempt,
                    "attempts": attempts,
                    "hwnd_health_before": health_before,
                    "hwnd_health_after": self.check_health(),
                    "hwnd_rebound": rebound,
                    "errors": errors,
                }
                result = OrderResult(
                    order_id=local_id,
                    status=OrderStatus.FAILED,
                    ticker=ticker,
                    side=side,
                    price=price,
                    quantity=quantity,
                    channel=self.channel_name,
                    message=f"submit_failed:{_truncate_text(err_text, 240)};diag={_compact_json(diag)}",
                )
                break

        if result is None:
            result = OrderResult(
                order_id=local_id,
                status=OrderStatus.FAILED,
                ticker=ticker,
                side=side,
                price=price,
                quantity=quantity,
                channel=self.channel_name,
                message="submit_failed:unknown",
            )
        self._local_orders[local_id] = result
        return result

    def _next_local_order_id(self) -> str:
        self._local_order_seq += 1
        return f"ths-auto-{int(time.time() * 1000)}-{self._local_order_seq}"

    def _find_local_order_id_by_broker_id(self, broker_order_id: str) -> str:
        if not broker_order_id:
            return ""
        for local_id, order in self._local_orders.items():
            if extract_broker_order_id(order.message) == broker_order_id:
                return local_id
        return ""

    def _rebind_hwnd(self, *, log_prefix: str = "runtime") -> bool:
        try:
            apps = Desktop(backend="win32").windows()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[%s] HWND 重绑定失败(%s): %s", self.channel_name, log_prefix, exc)
            return False

        candidates: list[tuple[int, str]] = []
        for app in apps:
            title = str(app.window_text() or "").strip()
            title_lower = title.lower()
            if any(token in title for token in ("股票", "交易", "委托")) or "xiadan" in title_lower:
                candidates.append((int(app.handle), title))
        if not candidates:
            logger.warning("[%s] HWND 重绑定未找到候选窗口(%s)", self.channel_name, log_prefix)
            return False

        old_hwnd = self.hwnd
        old_title = self.window_title
        self.hwnd, self.window_title = candidates[0]
        logger.info(
            "[%s] HWND 重绑定成功(%s): old=(%s,%s) new=(%s,%s)",
            self.channel_name,
            log_prefix,
            old_hwnd,
            old_title,
            self.hwnd,
            self.window_title,
        )
        return True


def _cancel_result_ok(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, dict):
        message = str(raw.get("message", "")).strip().lower()
        if any(token in message for token in ("success", "成功", "已撤", "撤单")):
            return True
        return bool(raw.get("success", False))
    text = str(raw or "").strip().lower()
    return any(token in text for token in ("success", "成功", "已撤", "撤单"))


def _map_status(status: str) -> OrderStatus:
    text = str(status or "").strip().lower()
    if text in {"filled", "all_traded"}:
        return OrderStatus.FILLED
    if text in {"partial", "part_traded"}:
        return OrderStatus.PARTIAL
    if text in {"cancelled", "canceled"}:
        return OrderStatus.CANCELLED
    if text in {"rejected", "failed"}:
        return OrderStatus.REJECTED
    if text in {"submitted", "pending"}:
        return OrderStatus.SUBMITTED
    return OrderStatus.PENDING


def _is_true(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _safe_compact(payload: Any) -> str:
    try:
        text = str(payload) if isinstance(payload, (str, bytes)) else str(payload)
        return _truncate_text(text, 480)
    except Exception:  # noqa: BLE001
        return ""


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _truncate_text(text: str, max_len: int) -> str:
    raw = str(text or "")
    if len(raw) <= max_len:
        return raw
    return raw[: max_len - 3] + "..."


def _compact_json(payload: Any) -> str:
    try:
        return _truncate_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), 800)
    except Exception:  # noqa: BLE001
        return ""


def _extract_local_broker_order_id(message: str) -> str:
    text = str(message or "")
    for marker in ("broker_order_id=", "order_id=", "entrust_no="):
        if marker in text:
            value = text.split(marker, 1)[1].split(";", 1)[0].strip()
            if value:
                return value
    return extract_broker_order_id(text)


def _is_transient_submit_error(error_text: str, tokens: tuple[str, ...]) -> bool:
    text = str(error_text or "").strip().lower()
    if not text:
        return False
    return any(token in text for token in tokens)


_DEFAULT_TRANSIENT_SUBMIT_TOKENS: tuple[str, ...] = (
    "timed out",
    "timeout",
    "超时",
    "busy",
    "暂时",
    "try again",
    "重试",
    "captcha",
    "验证码",
    "focus",
    "window",
    "控件",
)
