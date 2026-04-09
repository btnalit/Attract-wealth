from __future__ import annotations

import configparser
import json
import socket
from io import StringIO
from pathlib import Path
from typing import Any

AUTOSTART_MARK_BEGIN = "# [LAICAI_BRIDGE_AUTOSTART_BEGIN]"
AUTOSTART_MARK_END = "# [LAICAI_BRIDGE_AUTOSTART_END]"
DEFAULT_THS_ROOT = Path(r"D:\同花顺软件\同花顺")
DEFAULT_BRIDGE_HOST = "127.0.0.1"
DEFAULT_BRIDGE_PORT = 8089


def detect_newline(content: str) -> str:
    if "\r\n" in content:
        return "\r\n"
    return "\n"


def detect_text_encoding(path: Path) -> str:
    for encoding in ("utf-8", "gbk", "utf-16", "utf-16-le", "utf-16-be"):
        try:
            path.read_text(encoding=encoding)
            return encoding
        except Exception:  # noqa: BLE001
            continue
    return "utf-8"


def read_text_with_fallback(path: Path) -> tuple[str, str]:
    encoding = detect_text_encoding(path)
    try:
        return path.read_text(encoding=encoding), encoding
    except Exception:
        return path.read_text(encoding=encoding, errors="ignore"), encoding


def build_autostart_injection_block(newline: str = "\n") -> str:
    rows = [
        AUTOSTART_MARK_BEGIN,
        "try:",
        "    from laicai_host_bootstrap import ensure_laicai_bridge_autostart",
        "    ensure_laicai_bridge_autostart()",
        "except Exception as _laicai_bootstrap_exc:",
        "    try:",
        "        print('[laicai] bridge autostart bootstrap failed:', _laicai_bootstrap_exc)",
        "    except Exception:",
        "        pass",
        AUTOSTART_MARK_END,
    ]
    return newline.join(rows)


def inject_autostart_block(content: str, *, anchor: str = "from ths_api import *") -> str:
    newline = detect_newline(content)
    block = build_autostart_injection_block(newline=newline)

    begin = content.find(AUTOSTART_MARK_BEGIN)
    end = content.find(AUTOSTART_MARK_END)
    if begin >= 0 and end >= begin:
        end += len(AUTOSTART_MARK_END)
        return f"{content[:begin]}{block}{content[end:]}"

    anchor_idx = content.find(anchor)
    if anchor_idx < 0:
        if content.endswith(("\n", "\r")):
            return f"{content}{newline}{block}{newline}"
        return f"{content}{newline}{newline}{block}{newline}"

    line_end = content.find(newline, anchor_idx)
    if line_end < 0:
        return f"{content}{newline}{newline}{block}{newline}"
    insertion = line_end + len(newline)
    return f"{content[:insertion]}{newline}{block}{newline}{content[insertion:]}"


def render_host_bootstrap_script() -> str:
    return """# -*- coding: utf-8 -*-
from __future__ import annotations

import socket
import threading
import time

_BRIDGE_THREAD = None


def _port_ready(host: str, port: int, timeout_s: float = 0.6) -> bool:
    sock = socket.socket()
    sock.settimeout(timeout_s)
    try:
        sock.connect((host, int(port)))
        return True
    except Exception:
        return False
    finally:
        try:
            sock.close()
        except Exception:
            pass


def ensure_laicai_bridge_autostart(host: str = "127.0.0.1", port: int = 8089, wait_s: float = 3.0) -> dict:
    global _BRIDGE_THREAD

    if _port_ready(host, int(port)):
        return {"status": "already_ready", "ready": True}

    if _BRIDGE_THREAD is not None and _BRIDGE_THREAD.is_alive():
        deadline = time.time() + max(0.5, float(wait_s))
        while time.time() < deadline:
            if _port_ready(host, int(port)):
                return {"status": "already_starting", "ready": True}
            time.sleep(0.2)
        return {"status": "already_starting", "ready": False}

    import laicai_bridge as _bridge

    run_server = getattr(_bridge, "run_server", None)
    if run_server is None:
        return {"status": "missing_run_server", "ready": False}

    _BRIDGE_THREAD = threading.Thread(target=run_server, name="laicai-ths-bridge", daemon=True)
    _BRIDGE_THREAD.start()

    deadline = time.time() + max(0.5, float(wait_s))
    while time.time() < deadline:
        if _port_ready(host, int(port)):
            return {"status": "started", "ready": True}
        time.sleep(0.2)
    return {"status": "start_timeout", "ready": False}
"""


def _json_socket_request(
    payload: dict[str, Any],
    *,
    host: str = DEFAULT_BRIDGE_HOST,
    port: int = DEFAULT_BRIDGE_PORT,
    timeout_s: float = 1.5,
) -> dict[str, Any]:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    sock = socket.socket()
    sock.settimeout(timeout_s)
    try:
        sock.connect((host, int(port)))
        sock.sendall(raw)
        chunks: list[bytes] = []
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
        if not chunks:
            return {
                "ok": False,
                "reachable": True,
                "error": "empty response",
                "response": {},
            }
        response = json.loads(b"".join(chunks).decode("utf-8"))
        return {
            "ok": True,
            "reachable": True,
            "error": "",
            "response": response,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "reachable": False,
            "error": str(exc),
            "response": {},
        }
    finally:
        try:
            sock.close()
        except Exception:
            pass


def bridge_request(
    action: str,
    *,
    payload: dict[str, Any] | None = None,
    host: str = DEFAULT_BRIDGE_HOST,
    port: int = DEFAULT_BRIDGE_PORT,
    timeout_s: float = 1.5,
) -> dict[str, Any]:
    req = dict(payload or {})
    req["action"] = str(action or "").strip()
    return _json_socket_request(req, host=host, port=port, timeout_s=timeout_s)


def probe_bridge_runtime(host: str = "127.0.0.1", port: int = 8089, timeout_s: float = 1.5) -> dict[str, Any]:
    request = bridge_request("ping", host=host, port=port, timeout_s=timeout_s)
    if not request.get("ok", False):
        return {
            "reachable": bool(request.get("reachable", False)),
            "runtime_ok": False,
            "runtime": {},
            "error": str(request.get("error", "")),
            "response": request.get("response", {}),
        }
    response = request.get("response", {}) if isinstance(request.get("response", {}), dict) else {}
    runtime = response.get("runtime", {}) if isinstance(response.get("runtime", {}), dict) else {}
    runtime_ok = bool(runtime.get("in_ths_api") or runtime.get("in_xiadan_api"))
    return {
        "reachable": True,
        "runtime_ok": runtime_ok,
        "runtime": runtime,
        "error": "",
        "response": response,
    }


def fetch_trade_snapshot(
    *,
    host: str = DEFAULT_BRIDGE_HOST,
    port: int = DEFAULT_BRIDGE_PORT,
    timeout_s: float = 1.5,
) -> dict[str, Any]:
    return bridge_request("get_trade_snapshot", host=host, port=port, timeout_s=timeout_s)


def summarize_trade_snapshot(snapshot_response: dict[str, Any]) -> dict[str, Any]:
    response = snapshot_response.get("response", {}) if isinstance(snapshot_response.get("response", {}), dict) else {}
    data = response.get("data", {}) if isinstance(response.get("data", {}), dict) else {}
    balance = data.get("balance", {}) if isinstance(data.get("balance", {}), dict) else {}
    positions_raw = data.get("positions", {})
    open_orders_raw = data.get("open_orders", {})
    full_orders_raw = data.get("full_orders", {})

    positions_count = len(positions_raw) if isinstance(positions_raw, (dict, list, tuple, set)) else 0
    open_orders_count = len(open_orders_raw) if isinstance(open_orders_raw, (dict, list, tuple, set)) else 0
    full_orders_count = len(full_orders_raw) if isinstance(full_orders_raw, (dict, list, tuple, set)) else 0
    has_balance = any(key in balance for key in ("zjye", "kyje", "zzc", "zsz"))

    return {
        "snapshot_status": str(response.get("status", "")).lower(),
        "has_balance": bool(has_balance),
        "positions_count": int(positions_count),
        "open_orders_count": int(open_orders_count),
        "full_orders_count": int(full_orders_count),
        "balance_brief": {
            "zjye": balance.get("zjye"),
            "kyje": balance.get("kyje"),
            "zzc": balance.get("zzc"),
            "zsz": balance.get("zsz"),
        },
    }


def _load_ini(path: Path) -> configparser.ConfigParser:
    text, _ = read_text_with_fallback(path)
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    sanitized = text.replace("\x00", "")
    parser.read_file(StringIO(sanitized))
    return parser


def _parse_user_field(raw: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for pair in str(raw or "").split(";"):
        if "=" not in pair:
            continue
        key, value = pair.split("=", 1)
        key = key.strip().lower()
        value = value.strip()
        if key:
            result[key] = value
    return result


def read_ths_account_context(ths_root: Path = DEFAULT_THS_ROOT) -> dict[str, Any]:
    root = Path(ths_root).expanduser()
    users_ini = root / "users.ini"
    xiadan_ini = root / "xiadan.ini"

    info: dict[str, Any] = {
        "ths_root": str(root),
        "ths_root_exists": root.exists(),
        "users_ini_exists": users_ini.exists(),
        "xiadan_ini_exists": xiadan_ini.exists(),
        "last_userid": "",
        "last_user_name": "",
        "last_user_path": "",
        "ai_user_account": "",
        "sim_server_name": "",
        "mode_hint": "",
        "error": "",
    }
    if not root.exists():
        info["error"] = "ths_root_not_found"
        return info

    user_map: dict[str, dict[str, str]] = {}

    if users_ini.exists():
        try:
            parser = _load_ini(users_ini)
            if parser.has_section("user"):
                for userid, raw in parser.items("user"):
                    user_map[str(userid).strip()] = _parse_user_field(raw)
            info["last_userid"] = parser.get("last", "last_userid", fallback="").strip()
        except Exception as exc:  # noqa: BLE001
            info["error"] = f"users_ini_parse_failed: {exc}"

    if xiadan_ini.exists():
        try:
            parser = _load_ini(xiadan_ini)
            info["ai_user_account"] = parser.get("AI_TRADE", "AI_USER_ACCOUNT", fallback="").strip()
            info["sim_server_name"] = parser.get("356_WT_SERVER", "TCP/IP_NAME0", fallback="").strip()
        except Exception as exc:  # noqa: BLE001
            if not info.get("error"):
                info["error"] = f"xiadan_ini_parse_failed: {exc}"

    selected_userid = info["last_userid"] or info["ai_user_account"].replace("mx_", "", 1)
    selected = user_map.get(selected_userid, {})
    info["last_user_name"] = selected.get("name", "") or f"mx_{selected_userid}" if selected_userid else ""
    info["last_user_path"] = selected.get("path", "")

    server = str(info.get("sim_server_name", ""))
    account_name = str(info.get("last_user_name", "") or "")
    ai_account = str(info.get("ai_user_account", "") or "")
    if "模拟" in server or account_name.startswith("mx_") or ai_account.startswith("mx_"):
        info["mode_hint"] = "paper"
    elif server:
        info["mode_hint"] = "real_or_custom"
    else:
        info["mode_hint"] = "unknown"
    return info
