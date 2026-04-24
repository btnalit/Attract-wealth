from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from src.core.ths_host_autostart import probe_bridge_runtime

DEFAULT_THS_BRIDGE_SCRIPT = Path(r"D:\同花顺软件\同花顺\script\laicai_bridge.py")
DEFAULT_THS_BRIDGE_STDOUT = Path("data/smoke/reports/ths_bridge_stdout.log")
DEFAULT_THS_BRIDGE_STDERR = Path("data/smoke/reports/ths_bridge_stderr.log")


def _is_true(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _resolve_path(path_like: str | Path, project_root: Path) -> Path:
    path = Path(path_like).expanduser()
    if path.is_absolute():
        return path
    return (project_root / path).resolve()


def _wait_port(host: str, port: int, timeout_s: float) -> tuple[bool, str]:
    deadline = time.time() + max(0.2, float(timeout_s))
    last_error = ""
    while time.time() < deadline:
        sock = socket.socket()
        sock.settimeout(1.0)
        try:
            sock.connect((host, port))
            return True, ""
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            time.sleep(0.25)
        finally:
            try:
                sock.close()
            except Exception:  # noqa: BLE001
                pass
    return False, last_error or "timeout"


class THSBridgeRuntime:
    """Owns an optional local THS bridge process for the current app lifecycle."""

    def __init__(self, project_root: Path | None = None):
        self.project_root = project_root or Path(__file__).resolve().parents[2]
        self._proc: subprocess.Popen[Any] | None = None
        self._stdout_handle = None
        self._stderr_handle = None
        self._state: dict[str, Any] = {
            "enabled": False,
            "requested": False,
            "started": False,
            "existing": False,
            "owned": False,
            "ready": False,
            "pid": None,
            "host": "",
            "port": 0,
            "script": "",
            "python": "",
            "stdout_log": "",
            "stderr_log": "",
            "message": "not_started",
            "stopped": False,
            "require_host_runtime": True,
            "runtime_probe": {},
        }

    def start(self, *, channel: str, allow_disabled: bool = False) -> dict[str, Any]:
        selected = str(channel or "").strip().lower()
        auto_start = _is_true(os.getenv("STARTUP_AUTO_START_THS_BRIDGE"), default=True)
        host = os.getenv("THS_IPC_HOST", "127.0.0.1").strip() or "127.0.0.1"
        port = int(os.getenv("THS_IPC_PORT", "8089"))
        timeout_s = float(os.getenv("THS_BRIDGE_START_TIMEOUT_S", "12"))
        start_command = os.getenv("THS_BRIDGE_START_COMMAND", "").strip()
        require_host_runtime = _is_true(os.getenv("STARTUP_REQUIRE_THS_HOST_RUNTIME"), default=True)

        script = _resolve_path(
            os.getenv("THS_BRIDGE_SCRIPT", str(DEFAULT_THS_BRIDGE_SCRIPT)),
            project_root=self.project_root,
        )
        python_exec = os.getenv("THS_BRIDGE_PYTHON", "").strip() or sys.executable
        stdout_log = _resolve_path(
            os.getenv("THS_BRIDGE_STDOUT", str(DEFAULT_THS_BRIDGE_STDOUT)),
            project_root=self.project_root,
        )
        stderr_log = _resolve_path(
            os.getenv("THS_BRIDGE_STDERR", str(DEFAULT_THS_BRIDGE_STDERR)),
            project_root=self.project_root,
        )

        self._state = {
            "enabled": auto_start,
            "requested": bool(selected == "ths_ipc" and auto_start),
            "started": False,
            "existing": False,
            "owned": False,
            "ready": False,
            "pid": None,
            "host": host,
            "port": port,
            "script": str(script),
            "python": python_exec,
            "stdout_log": str(stdout_log),
            "stderr_log": str(stderr_log),
            "start_command": start_command,
            "message": "not_requested",
            "stopped": False,
            "require_host_runtime": require_host_runtime,
            "runtime_probe": {},
        }

        if selected != "ths_ipc":
            self._state["message"] = f"channel={selected}, skip bridge bootstrap"
            return dict(self._state)

        if not auto_start and not allow_disabled:
            self._state["message"] = "STARTUP_AUTO_START_THS_BRIDGE=false"
            return dict(self._state)

        already_ready, _ = _wait_port(host, port, timeout_s=0.25)
        if already_ready:
            self._state["existing"] = True
            runtime_probe = probe_bridge_runtime(host=host, port=port, timeout_s=1.2)
            runtime_ok = bool(runtime_probe.get("runtime_ok", False))
            self._state["runtime_probe"] = runtime_probe
            self._state["ready"] = bool(runtime_ok or not require_host_runtime)
            if require_host_runtime and not runtime_ok:
                self._state["message"] = "bridge already listening but runtime is not THS host"
            else:
                self._state["message"] = "bridge already listening"
            return dict(self._state)

        if not start_command and not script.exists():
            self._state["message"] = f"bridge script not found: {script}"
            return dict(self._state)

        try:
            stdout_log.parent.mkdir(parents=True, exist_ok=True)
            stderr_log.parent.mkdir(parents=True, exist_ok=True)
            self._stdout_handle = stdout_log.open("a", encoding="utf-8")
            self._stderr_handle = stderr_log.open("a", encoding="utf-8")
            if start_command:
                self._proc = subprocess.Popen(
                    start_command,
                    cwd=str(self.project_root),
                    stdout=self._stdout_handle,
                    stderr=self._stderr_handle,
                    shell=True,
                )
            else:
                self._proc = subprocess.Popen(
                    [python_exec, str(script)],
                    cwd=str(script.parent),
                    stdout=self._stdout_handle,
                    stderr=self._stderr_handle,
                )
            self._state["started"] = True
            self._state["owned"] = True
            self._state["pid"] = self._proc.pid
        except Exception as exc:  # noqa: BLE001
            self._state["message"] = f"bridge start failed: {exc}"
            self._close_logs()
            return dict(self._state)

        ready, reason = _wait_port(host, port, timeout_s=timeout_s)
        if ready:
            runtime_probe = probe_bridge_runtime(host=host, port=port, timeout_s=1.2)
            runtime_ok = bool(runtime_probe.get("runtime_ok", False))
            self._state["runtime_probe"] = runtime_probe
            if require_host_runtime and not runtime_ok:
                self._state["message"] = "bridge started but runtime is not THS host"
                self._state["ready"] = False
                self.stop(force=True, reason="runtime_not_host")
                return dict(self._state)

            self._state["ready"] = True
            self._state["message"] = "bridge started and ready"
            return dict(self._state)

        self._state["message"] = f"bridge started but port not ready: {reason}"
        self.stop(force=True, reason="startup_not_ready")
        return dict(self._state)

    def stop(self, *, force: bool = False, reason: str = "shutdown") -> dict[str, Any]:
        keep_bridge = _is_true(os.getenv("STARTUP_KEEP_THS_BRIDGE"), default=False)
        should_stop = bool(self._state.get("owned", False)) and (force or not keep_bridge)
        stopped = False

        if should_stop and self._proc is not None:
            try:
                if self._proc.poll() is None:
                    self._proc.terminate()
                    try:
                        self._proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        self._proc.kill()
                stopped = True
            except Exception:  # noqa: BLE001
                stopped = False

        self._close_logs()
        self._proc = None
        self._state["stopped"] = stopped
        self._state["shutdown_reason"] = reason
        self._state["keep_bridge"] = keep_bridge
        return dict(self._state)

    def snapshot(self) -> dict[str, Any]:
        return dict(self._state)

    def _close_logs(self) -> None:
        for handle_name in ("_stdout_handle", "_stderr_handle"):
            handle = getattr(self, handle_name, None)
            if handle is None:
                continue
            try:
                handle.flush()
                handle.close()
            except Exception:  # noqa: BLE001
                pass
            setattr(self, handle_name, None)
