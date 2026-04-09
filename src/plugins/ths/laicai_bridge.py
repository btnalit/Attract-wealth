# -*- coding: utf-8 -*-
"""
LaiCai THS IPC bridge.

部署方式：
1. 将本文件复制到 `D:\\同花顺软件\\同花顺\\script\\laicai_bridge.py`
2. 在同花顺交易客户端内执行脚本
3. 来财通过本地 8089 端口访问交易能力与交易域快照数据
"""

from __future__ import annotations

import json
import socket
import threading
import time
import traceback
from typing import Any

try:
    from ths_api import *  # noqa: F403,F401

    IN_THS_API = True
except ImportError:
    IN_THS_API = False

try:
    import xiadan as xd

    IN_XIADAN_API = True
except ImportError:
    IN_XIADAN_API = False

HOST = "127.0.0.1"
PORT = 8089
ORDER_STORE: dict[str, dict[str, Any]] = {}

SOURCE_PRIORITY = {
    "g_fullorder": 30,
    "g_order": 20,
    "local_store": 10,
}


def execute_cmd(cmd_str: str) -> dict[str, Any]:
    """调用同花顺下单命令。"""
    print(f"[*] 执行底层交易命令: {cmd_str}")
    if IN_THS_API and "xd" in globals():
        return _ensure_dict(xd.cmd(cmd_str))
    if IN_XIADAN_API:
        return _ensure_dict(xd.cmd(cmd_str))
    print("[WARNING] 当前不在同花顺交易宿主中，返回 mock 结果。")
    return {"retcode": "0", "retmsg": "Mock Success", "cmd": cmd_str}


def get_ths_global(var_name: str) -> Any:
    """
    读取 xiadan 全局对象。
    既支持 `xd.xxx` 也支持 `xd.g_xxx`。
    """
    if IN_XIADAN_API:
        try:
            val = getattr(xd, var_name, getattr(xd, f"g_{var_name}", None))
            if val is not None:
                return val
        except Exception:
            pass
    return {}


def _ensure_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


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


def _normalize_side(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    if any(token in text for token in ("sell", "卖", "s")):
        return "SELL"
    return "BUY"


def _normalize_status(raw_status: Any, status_text: Any, filled_qty: int, qty: int, cancel_qty: int) -> str:
    text = f"{raw_status or ''} {status_text or ''}".strip().lower()
    if filled_qty > 0 and qty > 0 and filled_qty >= qty:
        return "filled"
    if any(token in text for token in ("全成", "全部成交", "已成", "dealed", "filled", "all_traded")):
        return "filled"
    if any(token in text for token in ("部成", "部分成交", "part_traded", "partial")):
        return "partial"
    if cancel_qty > 0 and filled_qty > 0 and qty > filled_qty:
        return "partial"
    if any(token in text for token in ("已撤", "撤单", "canceled", "cancelled", "cancel")):
        return "cancelled"
    if any(token in text for token in ("废单", "拒单", "rejected", "failed", "error")):
        return "rejected"
    if any(token in text for token in ("未成", "已报", "submitted", "pending", "排队", "申报")):
        return "submitted"
    if filled_qty > 0:
        return "partial"
    return "pending"


def _iter_order_candidates(raw_orders: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(raw_orders, list):
        for item in raw_orders:
            if isinstance(item, dict):
                rows.append(dict(item))
        return rows

    if not isinstance(raw_orders, dict):
        return rows

    for key, value in raw_orders.items():
        if isinstance(value, list):
            for row in value:
                if isinstance(row, dict):
                    item = dict(row)
                    if not item.get("zqdm"):
                        item["zqdm"] = str(key)
                    rows.append(item)
            continue
        if isinstance(value, dict):
            item = dict(value)
            if not item.get("zqdm"):
                key_text = str(key or "").strip()
                if key_text.isdigit() and len(key_text) <= 8:
                    item["zqdm"] = key_text
            if not item.get("htbh"):
                key_text = str(key or "").strip()
                if key_text and key_text.isdigit() and len(key_text) > 8:
                    item["htbh"] = key_text
            rows.append(item)
    return rows


def _normalize_orders(raw_orders: Any, *, source: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in _iter_order_candidates(raw_orders):
        qty = _to_int(raw.get("wtsl") or raw.get("quantity"))
        filled_qty = _to_int(raw.get("cjsl") or raw.get("filled_quantity"))
        cancel_qty = _to_int(raw.get("cxsl") or raw.get("cancel_quantity"))
        status_raw = raw.get("status")
        status_text = raw.get("bz")

        row = {
            "client_order_id": str(raw.get("client_order_id") or "").strip(),
            "order_id": str(raw.get("htbh") or raw.get("order_id") or "").strip(),
            "ticker": str(raw.get("zqdm") or raw.get("ticker") or raw.get("code") or "").strip(),
            "side": _normalize_side(raw.get("cz") or raw.get("side")),
            "price": _to_float(raw.get("wtjg") or raw.get("price")),
            "filled_price": _to_float(raw.get("cjjj") or raw.get("filled_price")),
            "quantity": qty,
            "filled_quantity": filled_qty,
            "status": _normalize_status(status_raw, status_text, filled_qty, qty, cancel_qty),
            "status_raw": str(status_raw or "").strip(),
            "status_text": str(status_text or "").strip(),
            "cancel_quantity": cancel_qty,
            "order_date": str(raw.get("wtrq") or "").strip(),
            "order_time": str(raw.get("wtsj") or "").strip(),
            "market": str(raw.get("jysc") or "").strip(),
            "account": str(raw.get("gdzh") or "").strip(),
            "source": source,
            "timestamp": _to_float(raw.get("timestamp") or time.time()),
        }
        rows.append(row)
    return rows


def _merge_orders(*order_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for rows in order_groups:
        for row in rows:
            key = str(row.get("order_id") or row.get("client_order_id") or "").strip()
            if not key:
                key = f"tmp-{row.get('ticker', '')}-{int(_to_float(row.get('timestamp')) * 1000)}"
            existing = merged.get(key)
            if not existing:
                merged[key] = dict(row)
                continue
            old_priority = SOURCE_PRIORITY.get(str(existing.get("source")), 0)
            new_priority = SOURCE_PRIORITY.get(str(row.get("source")), 0)
            if new_priority >= old_priority:
                merged[key] = dict(row)
                continue

            # 补全旧记录缺失字段
            for field in ("order_id", "client_order_id", "ticker", "side", "status", "status_raw", "status_text"):
                if not existing.get(field) and row.get(field):
                    existing[field] = row.get(field)
            for field in ("price", "filled_price", "quantity", "filled_quantity", "cancel_quantity"):
                if _to_float(existing.get(field)) <= 0 and _to_float(row.get(field)) > 0:
                    existing[field] = row.get(field)
    return list(merged.values())


def _build_orders_payload(mode: str, include_local_store: bool = True) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    mode_text = (mode or "full").strip().lower()
    open_orders = _normalize_orders(get_ths_global("order"), source="g_order")
    full_orders = _normalize_orders(get_ths_global("fullorder"), source="g_fullorder")
    local_orders = _normalize_orders(list(ORDER_STORE.values()), source="local_store")

    if mode_text == "open":
        rows = _merge_orders(open_orders, local_orders if include_local_store else [])
    elif mode_text == "all":
        rows = _merge_orders(full_orders, open_orders, local_orders if include_local_store else [])
    else:
        rows = _merge_orders(full_orders, open_orders, local_orders if include_local_store else [])
        mode_text = "full"

    meta = {
        "mode": mode_text,
        "counts": {
            "open": len(open_orders),
            "full": len(full_orders),
            "local": len(local_orders),
            "merged": len(rows),
        },
        "runtime": {
            "in_ths_api": IN_THS_API,
            "in_xiadan_api": IN_XIADAN_API,
        },
    }
    return rows, meta


def process_request(req_data: dict[str, Any]) -> dict[str, Any]:
    try:
        action = str(req_data.get("action") or "").strip()
        if action == "ping":
            return {
                "status": "ok",
                "message": "THS IPC Bridge is active.",
                "runtime": {
                    "in_ths_api": IN_THS_API,
                    "in_xiadan_api": IN_XIADAN_API,
                },
            }

        if action == "get_balance":
            return {"status": "success", "data": get_ths_global("money")}

        if action == "get_positions":
            return {"status": "success", "data": get_ths_global("position")}

        if action in {"get_orders", "get_open_orders", "get_full_orders"}:
            mode = "full"
            if action == "get_open_orders":
                mode = "open"
            elif action == "get_orders":
                mode = str(req_data.get("mode") or "full")
            include_local = bool(req_data.get("include_local_store", True))
            rows, meta = _build_orders_payload(mode=mode, include_local_store=include_local)
            return {"status": "success", "data": rows, "meta": meta}

        if action == "get_order_summary":
            return {"status": "success", "data": get_ths_global("ordersum")}

        if action == "get_trade_snapshot":
            open_rows, open_meta = _build_orders_payload(mode="open")
            full_rows, full_meta = _build_orders_payload(mode="full")
            return {
                "status": "success",
                "data": {
                    "balance": get_ths_global("money"),
                    "positions": get_ths_global("position"),
                    "open_orders": open_rows,
                    "full_orders": full_rows,
                    "order_summary": get_ths_global("ordersum"),
                },
                "meta": {
                    "open_orders": open_meta,
                    "full_orders": full_meta,
                },
            }

        if action in {"buy", "sell"}:
            ticker = str(req_data.get("ticker") or "").strip()
            if not ticker:
                return {"status": "error", "message": "ticker is required"}
            price = req_data.get("price", "zxjg")
            qty = _to_int(req_data.get("qty", 100))
            client_order_id = str(req_data.get("client_order_id") or f"ths-{int(time.time() * 1000)}")
            cmd_str = f"{action} {ticker} {price} {qty} -notip"
            res = execute_cmd(cmd_str)
            order_id = str(res.get("htbh") or res.get("order_id") or "").strip()
            retcode = str(res.get("retcode", "0")).strip()
            ok = retcode in {"", "0"}

            ORDER_STORE[client_order_id] = {
                "client_order_id": client_order_id,
                "order_id": order_id,
                "ticker": ticker,
                "side": "BUY" if action == "buy" else "SELL",
                "price": _to_float(price),
                "quantity": qty,
                "filled_quantity": 0,
                "filled_price": 0.0,
                "status": "submitted" if ok else "failed",
                "status_raw": retcode,
                "timestamp": time.time(),
            }

            if not ok:
                return {
                    "status": "error",
                    "message": str(res.get("retmsg") or "submit failed"),
                    "trade_result": {
                        "order_id": order_id,
                        "client_order_id": client_order_id,
                        "retcode": retcode,
                    },
                    "raw": res,
                }
            return {
                "status": "success",
                "trade_result": {"order_id": order_id, "client_order_id": client_order_id},
                "raw": res,
            }

        if action == "cancel":
            client_order_id = str(req_data.get("client_order_id") or "").strip()
            htbh = str(req_data.get("order_id") or "").strip()
            if htbh:
                cmd_str = f"cancel -h {htbh}"
            else:
                ticker = str(req_data.get("ticker") or "").strip()
                direction = str(req_data.get("direction") or "").strip()
                cmd_str = f"cancel {ticker} {direction}".strip()
            res = execute_cmd(cmd_str)
            retcode = str(res.get("retcode", "0")).strip()
            ok = retcode in {"", "0"}
            if ok and client_order_id and client_order_id in ORDER_STORE:
                ORDER_STORE[client_order_id]["status"] = "cancelled"
            if not ok:
                return {"status": "error", "message": str(res.get("retmsg") or "cancel failed"), "trade_result": res}
            return {"status": "success", "trade_result": res}

        return {"status": "error", "message": f"Unknown action: {action}"}
    except Exception as exc:  # noqa: BLE001
        err_msg = traceback.format_exc()
        return {"status": "error", "message": str(exc), "traceback": err_msg}


def handle_client(conn: socket.socket, addr: tuple[str, int]) -> None:
    print(f"[+] 接收到连接: {addr}")
    try:
        data = conn.recv(10240)
        if data:
            req_data = _ensure_dict(json.loads(data.decode("utf-8").strip()))
            print(f"[<] 收到指令: {req_data}")
            response_data = process_request(req_data)
            conn.sendall(json.dumps(response_data, ensure_ascii=False).encode("utf-8"))
            print("[>] 指令处理完成。")
    except Exception as exc:  # noqa: BLE001
        print(f"[-] 客户端请求处理失败: {exc}")
    finally:
        conn.close()


def run_server() -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(5)
    print("=====================================")
    print("[来财] THS IPC Bridge 已启动")
    print(f"[来财] 监听端口: {HOST}:{PORT}")
    print("=====================================")

    while True:
        conn, addr = server.accept()
        client_thread = threading.Thread(target=handle_client, args=(conn, addr))
        client_thread.daemon = True
        client_thread.start()


if __name__ == "__main__":
    run_server()
