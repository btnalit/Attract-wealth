from __future__ import annotations

import csv
import configparser
import json
import subprocess
import socket
from io import StringIO
from pathlib import Path
from typing import Any

AUTOSTART_MARK_BEGIN = "# [LAICAI_BRIDGE_AUTOSTART_BEGIN]"
AUTOSTART_MARK_END = "# [LAICAI_BRIDGE_AUTOSTART_END]"
DEFAULT_THS_ROOT = Path(r"D:\同花顺软件\同花顺")
DEFAULT_BRIDGE_HOST = "127.0.0.1"
DEFAULT_BRIDGE_PORT = 8089
OBS_DIR_NAME = "_laicai_obs"
MY_SIGNALS_MARKER_FILE = "my_signals_exec.jsonl"
MY_SIGNALS_ERROR_FILE = "my_signals_error.log"
BOOTSTRAP_MARKER_FILE = "bootstrap_exec.jsonl"
BOOTSTRAP_ERROR_FILE = "bootstrap_error.log"
DEFAULT_STRATEGY_WINDOW_KEYWORDS = ("策略条件单", "信号策略", "条件单", "策略预警")


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
        "    import json as _laicai_json",
        "    import os as _laicai_os",
        "    import time as _laicai_time",
        "    import traceback as _laicai_traceback",
        "",
        "    def _laicai_obs_append(filename, payload):",
        "        _laicai_base_dir = _laicai_os.path.dirname(_laicai_os.path.abspath(__file__))",
        "        _laicai_obs_dir = _laicai_os.path.join(_laicai_base_dir, '_laicai_obs')",
        "        try:",
        "            if not _laicai_os.path.exists(_laicai_obs_dir):",
        "                _laicai_os.makedirs(_laicai_obs_dir)",
        "        except Exception:",
        "            return",
        "        _laicai_marker_path = _laicai_os.path.join(_laicai_obs_dir, filename)",
        "        try:",
        "            with open(_laicai_marker_path, 'a') as _laicai_fp:",
        "                _laicai_fp.write(_laicai_json.dumps(payload, ensure_ascii=False))",
        "                _laicai_fp.write('\\n')",
        "        except Exception:",
        "            pass",
        "",
        "    _laicai_obs_append('my_signals_exec.jsonl', {'stage': 'my_signals_enter', 'ts': _laicai_time.time()})",
        "    from laicai_host_bootstrap import ensure_laicai_bridge_autostart",
        "    _laicai_bootstrap_result = ensure_laicai_bridge_autostart()",
        "    _laicai_obs_append('my_signals_exec.jsonl', {'stage': 'my_signals_exit', 'ts': _laicai_time.time(), 'result': _laicai_bootstrap_result})",
        "except Exception as _laicai_bootstrap_exc:",
        "    try:",
        "        import os as _laicai_os",
        "        import traceback as _laicai_traceback",
        "        _laicai_base_dir = _laicai_os.path.dirname(_laicai_os.path.abspath(__file__))",
        "        _laicai_obs_dir = _laicai_os.path.join(_laicai_base_dir, '_laicai_obs')",
        "        if not _laicai_os.path.exists(_laicai_obs_dir):",
        "            _laicai_os.makedirs(_laicai_obs_dir)",
        "        _laicai_error_path = _laicai_os.path.join(_laicai_obs_dir, 'my_signals_error.log')",
        "        with open(_laicai_error_path, 'a') as _laicai_fp:",
        "            _laicai_fp.write(_laicai_traceback.format_exc())",
        "            _laicai_fp.write('\\n')",
        "    except Exception:",
        "        pass",
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
import json
import os
import socket
import threading
import time
import traceback

_BRIDGE_THREAD = None
_OBS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_laicai_obs")
_BOOTSTRAP_MARKER = os.path.join(_OBS_DIR, "bootstrap_exec.jsonl")
_BOOTSTRAP_ERROR = os.path.join(_OBS_DIR, "bootstrap_error.log")


def _ensure_obs_dir():
    try:
        if not os.path.exists(_OBS_DIR):
            os.makedirs(_OBS_DIR)
        return True
    except Exception:
        return False


def _append_marker(stage, extra=None):
    payload = {
        "ts": time.time(),
        "pid": os.getpid(),
        "thread": threading.current_thread().name,
        "stage": str(stage or ""),
    }
    if isinstance(extra, dict):
        payload.update(extra)
    if not _ensure_obs_dir():
        return
    try:
        with open(_BOOTSTRAP_MARKER, "a") as fp:
            fp.write(json.dumps(payload, ensure_ascii=False))
            fp.write("\\n")
    except Exception:
        pass


def _persist_error(stage, exc):
    _append_marker("error", {"error_stage": str(stage or ""), "error": str(exc or "")})
    if not _ensure_obs_dir():
        return
    try:
        with open(_BOOTSTRAP_ERROR, "a") as fp:
            fp.write("[{}] stage={} error={}\\n".format(time.strftime("%Y-%m-%d %H:%M:%S"), stage, exc))
            fp.write(traceback.format_exc())
            fp.write("\\n")
    except Exception:
        pass


def _port_ready(host, port, timeout_s=0.6):
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


def ensure_laicai_bridge_autostart(host="127.0.0.1", port=8089, wait_s=3.0):
    global _BRIDGE_THREAD
    _append_marker("ensure_enter", {"host": str(host), "port": int(port), "wait_s": float(wait_s)})

    try:
        if _port_ready(host, int(port)):
            _append_marker("already_ready", {"ready": True})
            return {"status": "already_ready", "ready": True}

        if _BRIDGE_THREAD is not None and _BRIDGE_THREAD.is_alive():
            deadline = time.time() + max(0.5, float(wait_s))
            while time.time() < deadline:
                if _port_ready(host, int(port)):
                    _append_marker("already_starting", {"ready": True})
                    return {"status": "already_starting", "ready": True}
                time.sleep(0.2)
            _append_marker("already_starting_timeout", {"ready": False})
            return {"status": "already_starting", "ready": False}

        try:
            import laicai_bridge as _bridge
        except Exception as exc:
            _persist_error("import_bridge", exc)
            return {"status": "import_failed", "ready": False, "error": str(exc)}

        run_server = getattr(_bridge, "run_server", None)
        if run_server is None:
            _append_marker("missing_run_server", {"ready": False})
            return {"status": "missing_run_server", "ready": False}

        try:
            _BRIDGE_THREAD = threading.Thread(target=run_server, name="laicai-ths-bridge")
            _BRIDGE_THREAD.daemon = True
            _BRIDGE_THREAD.start()
            _append_marker("thread_started", {"thread_alive": bool(_BRIDGE_THREAD.is_alive())})
        except Exception as exc:
            _persist_error("start_thread", exc)
            return {"status": "start_exception", "ready": False, "error": str(exc)}

        deadline = time.time() + max(0.5, float(wait_s))
        while time.time() < deadline:
            if _port_ready(host, int(port)):
                _append_marker("started", {"ready": True})
                return {"status": "started", "ready": True}
            time.sleep(0.2)
        _append_marker("start_timeout", {"ready": False})
        return {"status": "start_timeout", "ready": False}
    except Exception as exc:
        _persist_error("ensure_uncaught", exc)
        return {"status": "ensure_exception", "ready": False, "error": str(exc)}
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


def _safe_mtime(path: Path) -> float:
    try:
        return float(path.stat().st_mtime)
    except Exception:
        return 0.0


def _safe_size(path: Path) -> int:
    try:
        return int(path.stat().st_size)
    except Exception:
        return 0


def _read_jsonl_tail(path: Path, max_lines: int = 20) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    text, _ = read_text_with_fallback(path)
    rows: list[dict[str, Any]] = []
    for line in text.splitlines()[-max(1, int(max_lines)) :]:
        raw = str(line or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                rows.append(data)
            else:
                rows.append({"raw": raw})
        except Exception:
            rows.append({"raw": raw})
    return rows


def _read_text_tail(path: Path, max_lines: int = 20) -> list[str]:
    if not path.exists():
        return []
    text, _ = read_text_with_fallback(path)
    lines = [str(line or "").rstrip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return lines[-max(1, int(max_lines)) :]


def _normalize_window_title(value: str) -> str:
    return "".join(ch for ch in str(value or "").lower() if not ch.isspace())


def _match_strategy_window_title(title: str, keywords: tuple[str, ...]) -> bool:
    normalized = _normalize_window_title(title)
    if not normalized:
        return False
    for keyword in keywords:
        token = _normalize_window_title(keyword)
        if token and token in normalized:
            return True
    return False


def is_xiadan_running() -> tuple[bool | None, str]:
    try:
        proc = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq xiadan.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            check=False,
            text=True,
            encoding="gbk",
            errors="ignore",
        )
        text = f"{proc.stdout}\n{proc.stderr}".strip().lower()
        if ("access denied" in text) or ("access is denied" in text):
            return None, "access_denied"
        if "no tasks are running" in text:
            return False, ""
        if "xiadan.exe" in text:
            return True, ""
        if proc.returncode != 0:
            return None, text.strip() or f"tasklist_rc={proc.returncode}"
        return False, ""
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def collect_xiadan_ui_context(
    strategy_window_keywords: tuple[str, ...] | list[str] | None = None,
) -> dict[str, Any]:
    keywords_raw = strategy_window_keywords or DEFAULT_STRATEGY_WINDOW_KEYWORDS
    keywords = tuple(str(item).strip() for item in keywords_raw if str(item).strip())
    context: dict[str, Any] = {
        "running": False,
        "process_count": 0,
        "strategy_page_open": False,
        "strategy_window_keywords": list(keywords),
        "strategy_related_windows": [],
        "window_titles": [],
        "processes": [],
        "error": "",
    }
    try:
        proc = subprocess.run(
            ["tasklist", "/V", "/FI", "IMAGENAME eq xiadan.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            check=False,
            text=True,
            encoding="gbk",
            errors="ignore",
        )
        raw_text = f"{proc.stdout}\n{proc.stderr}".strip()
        text_lower = raw_text.lower()
        if "access denied" in text_lower:
            context["error"] = "access_denied"
            return context
        if "no tasks are running" in text_lower:
            return context
        if not raw_text:
            if proc.returncode != 0:
                context["error"] = f"tasklist_rc={proc.returncode}"
            return context

        rows: list[dict[str, Any]] = []
        related_titles: list[str] = []
        for line in proc.stdout.splitlines():
            raw = str(line or "").strip()
            if not raw:
                continue
            try:
                row = next(csv.reader([raw]))
            except Exception:
                continue
            if len(row) < 9:
                continue
            if str(row[0]).strip().lower() != "xiadan.exe":
                continue
            pid_text = str(row[1]).strip().replace(",", "")
            try:
                pid = int(pid_text)
            except Exception:
                pid = 0
            window_title = str(row[8]).strip()
            rows.append(
                {
                    "pid": pid,
                    "session_name": str(row[2]).strip(),
                    "session_id": str(row[3]).strip(),
                    "mem_usage": str(row[4]).strip(),
                    "status": str(row[5]).strip(),
                    "user_name": str(row[6]).strip(),
                    "cpu_time": str(row[7]).strip(),
                    "window_title": window_title,
                }
            )
            if _match_strategy_window_title(window_title, keywords):
                related_titles.append(window_title)

        titles = [str(item.get("window_title", "")).strip() for item in rows if str(item.get("window_title", "")).strip()]
        context["running"] = bool(rows)
        context["process_count"] = len(rows)
        context["window_titles"] = titles
        context["processes"] = rows
        context["strategy_related_windows"] = related_titles
        context["strategy_page_open"] = bool(related_titles)
        return context
    except Exception as exc:  # noqa: BLE001
        context["error"] = str(exc)
        return context


def collect_host_observability_snapshot(ths_root: Path = DEFAULT_THS_ROOT, max_lines: int = 20) -> dict[str, Any]:
    root = Path(ths_root).expanduser()
    script_root = root / "script"
    obs_dir = script_root / OBS_DIR_NAME

    my_marker = obs_dir / MY_SIGNALS_MARKER_FILE
    my_error = obs_dir / MY_SIGNALS_ERROR_FILE
    bootstrap_marker = obs_dir / BOOTSTRAP_MARKER_FILE
    bootstrap_error = obs_dir / BOOTSTRAP_ERROR_FILE

    my_marker_tail = _read_jsonl_tail(my_marker, max_lines=max_lines)
    my_error_tail = _read_text_tail(my_error, max_lines=max_lines)
    bootstrap_marker_tail = _read_jsonl_tail(bootstrap_marker, max_lines=max_lines)
    bootstrap_error_tail = _read_text_tail(bootstrap_error, max_lines=max_lines)

    host_execution_evidence = bool(my_marker_tail or bootstrap_marker_tail)
    has_errors = bool(my_error_tail or bootstrap_error_tail)

    return {
        "ths_root": str(root),
        "script_root": str(script_root),
        "obs_dir": str(obs_dir),
        "obs_dir_exists": obs_dir.exists(),
        "host_execution_evidence": host_execution_evidence,
        "has_errors": has_errors,
        "my_signals": {
            "marker_path": str(my_marker),
            "marker_exists": my_marker.exists(),
            "marker_mtime": _safe_mtime(my_marker),
            "marker_size": _safe_size(my_marker),
            "marker_count": len(my_marker_tail),
            "last_marker": my_marker_tail[-1] if my_marker_tail else {},
            "marker_tail": my_marker_tail,
            "error_path": str(my_error),
            "error_exists": my_error.exists(),
            "error_mtime": _safe_mtime(my_error),
            "error_size": _safe_size(my_error),
            "error_tail": my_error_tail,
        },
        "bootstrap": {
            "marker_path": str(bootstrap_marker),
            "marker_exists": bootstrap_marker.exists(),
            "marker_mtime": _safe_mtime(bootstrap_marker),
            "marker_size": _safe_size(bootstrap_marker),
            "marker_count": len(bootstrap_marker_tail),
            "last_marker": bootstrap_marker_tail[-1] if bootstrap_marker_tail else {},
            "marker_tail": bootstrap_marker_tail,
            "error_path": str(bootstrap_error),
            "error_exists": bootstrap_error.exists(),
            "error_mtime": _safe_mtime(bootstrap_error),
            "error_size": _safe_size(bootstrap_error),
            "error_tail": bootstrap_error_tail,
        },
    }


def analyze_host_trigger_chain(
    snapshot: dict[str, Any],
    *,
    xiadan_running: bool | None = None,
    runtime_probe: dict[str, Any] | None = None,
    ui_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    obs = snapshot if isinstance(snapshot, dict) else {}
    runtime = runtime_probe if isinstance(runtime_probe, dict) else {}
    ui = ui_context if isinstance(ui_context, dict) else {}

    my_signals = obs.get("my_signals", {}) if isinstance(obs.get("my_signals", {}), dict) else {}
    bootstrap = obs.get("bootstrap", {}) if isinstance(obs.get("bootstrap", {}), dict) else {}

    my_tail = my_signals.get("marker_tail", []) if isinstance(my_signals.get("marker_tail", []), list) else []
    bootstrap_tail = bootstrap.get("marker_tail", []) if isinstance(bootstrap.get("marker_tail", []), list) else []

    def _has_stage(rows: list[dict[str, Any]], stage: str) -> bool:
        for row in rows:
            if isinstance(row, dict) and str(row.get("stage", "")) == str(stage):
                return True
        return False

    host_execution_evidence = bool(obs.get("host_execution_evidence", False))
    has_errors = bool(obs.get("has_errors", False))
    runtime_reachable = bool(runtime.get("reachable", False))
    runtime_ok = bool(runtime.get("runtime_ok", False))
    runtime_info = runtime.get("runtime", {}) if isinstance(runtime.get("runtime", {}), dict) else {}
    strategy_page_open = bool(ui.get("strategy_page_open", False))
    ui_titles = ui.get("window_titles", []) if isinstance(ui.get("window_titles", []), list) else []

    my_enter = _has_stage(my_tail, "my_signals_enter")
    my_exit = _has_stage(my_tail, "my_signals_exit")
    bootstrap_started = _has_stage(bootstrap_tail, "started")
    bootstrap_thread_started = _has_stage(bootstrap_tail, "thread_started")
    bootstrap_error_stage = _has_stage(bootstrap_tail, "error")

    stage = "UNKNOWN"
    status = "FAIL"
    summary = "无法确定宿主触发链路状态。"
    blockers: list[str] = []
    suggestions: list[str] = []

    if xiadan_running is False:
        stage = "NO_XIADAN_PROCESS"
        summary = "未检测到 xiadan.exe 进程，宿主脚本无执行上下文。"
        blockers.append("xiadan process not running")
        suggestions.append("先启动并登录同花顺交易客户端（xiadan.exe）。")
        suggestions.append("在交易会话中打开一次“策略条件单/信号策略”触发 my_signals.py。")
    elif not host_execution_evidence:
        if ui_titles and not strategy_page_open:
            stage = "UI_TRIGGER_PAGE_NOT_OPEN"
            summary = "THS 主会话存在，但未检测到“策略条件单/信号策略”页面窗口，触发链路未进入 my_signals。"
            blockers.append("strategy trigger page not open")
            suggestions.append("在同花顺交易会话内手动打开一次“策略条件单/信号策略”并保持窗口可见。")
            suggestions.append("打开后立即复跑 probe，确认 _laicai_obs marker 生成。")
        else:
            stage = "HOST_SCRIPT_NOT_TRIGGERED"
            summary = "未检测到 my_signals/bootstrap 执行 marker，宿主触发链路未启动。"
            blockers.append("host script marker missing")
            suggestions.append("确认当前登录会话为目标 THS 安装目录，并打开一次“策略条件单/信号策略”。")
            suggestions.append("触发后检查 script/_laicai_obs 下 marker 是否生成。")
    elif has_errors or bootstrap_error_stage:
        stage = "HOST_SCRIPT_ERROR"
        summary = "检测到宿主脚本异常持久化记录。"
        blockers.append("host script error persisted")
        suggestions.append("查看 my_signals_error.log/bootstrap_error.log 末尾堆栈并修复。")
        suggestions.append("修复后重启 xiadan 会话并再次触发策略脚本。")
    elif my_enter and not my_exit:
        stage = "MY_SIGNALS_INTERRUPTED"
        summary = "my_signals 已进入但未完成退出，触发链路中断。"
        blockers.append("my_signals interrupted before exit marker")
        suggestions.append("检查 my_signals.py 执行环境依赖与运行时异常。")
    elif runtime_ok:
        stage = "HOST_RUNTIME_READY"
        status = "PASS"
        summary = "已进入 THS 宿主 runtime。"
        suggestions.append("可继续执行 A36/A35/A34 全量守门。")
    elif runtime_reachable and not runtime_ok:
        stage = "BRIDGE_MOCK_RUNTIME"
        summary = "bridge 可达但 runtime 仍为 mock_runtime。"
        blockers.append("bridge reachable but runtime is not host")
        suggestions.append("确认 bridge 由宿主脚本拉起，而非外部进程独立启动。")
        suggestions.append("优先依据 marker 时间戳核对 my_signals/bootstrap 与 probe 时序。")
    elif my_exit and not (bootstrap_thread_started or bootstrap_started):
        stage = "BOOTSTRAP_NOT_EFFECTIVE"
        summary = "my_signals 已执行完成，但 bootstrap 未出现启动阶段 marker。"
        blockers.append("bootstrap not effective after my_signals exit")
        suggestions.append("检查 laicai_host_bootstrap.py 导入/调用路径与权限。")
    elif bootstrap_thread_started and not runtime_reachable:
        stage = "BRIDGE_NOT_LISTENING"
        summary = "bootstrap 已尝试启动 bridge，但探针未检测到端口监听。"
        blockers.append("bridge thread started but port unreachable")
        suggestions.append("检查 bridge 启动异常日志与端口占用情况。")
    else:
        stage = "HOST_TRIGGER_PENDING"
        summary = "链路已部分触发，但尚未进入稳定宿主 runtime。"
        suggestions.append("保持 xiadan 会话，重复触发一次策略页面后重试探针。")

    if status != "PASS" and not blockers:
        blockers.append("host trigger chain not ready")

    if stage != "HOST_RUNTIME_READY":
        status = "FAIL"

    return {
        "stage": stage,
        "status": status,
        "summary": summary,
        "blockers": blockers,
        "suggestions": suggestions,
        "facts": {
            "xiadan_running": xiadan_running,
            "strategy_page_open": strategy_page_open,
            "ui_window_title_count": len(ui_titles),
            "ui_window_titles": ui_titles,
            "host_execution_evidence": host_execution_evidence,
            "has_errors": has_errors,
            "my_marker_count": len(my_tail),
            "bootstrap_marker_count": len(bootstrap_tail),
            "my_signals_enter": my_enter,
            "my_signals_exit": my_exit,
            "bootstrap_thread_started": bootstrap_thread_started,
            "bootstrap_started": bootstrap_started,
            "runtime_reachable": runtime_reachable,
            "runtime_ok": runtime_ok,
            "runtime": runtime_info,
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
