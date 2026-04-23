# -*- coding: utf-8 -*-
"""
32-bit easytrader bridge proxy.

Provides:
- `discover_python32()`: auto-find a 32-bit Python executable
- `BridgeProxyClient`: drop-in replacement for easytrader client that
  proxies all calls to a 32-bit subprocess via JSON-over-stdin/stdout.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_BRIDGE_WORKER = Path(__file__).with_name("bridge_worker.py")

# Common 32-bit Python install locations on Windows
_PYTHON32_SCAN_PATTERNS = [
    r"C:\Users\{user}\AppData\Local\Programs\Python\Python3*-32\python.exe",
    r"C:\Python3*-32\python.exe",
    r"D:\Python3*-32\python.exe",
    r"C:\Program Files (x86)\Python3*\python.exe",
]


def discover_python32(explicit: str = "") -> str | None:
    """Find a 32-bit Python executable that can run easytrader.

    Priority:
    1. THS_EASYTRADER_PYTHON32 env var / explicit parameter
    2. Registry scan (winreg)
    3. Common filesystem paths

    Among candidates, prefer ones where easytrader is actually importable.
    """
    easytrader_repo = os.getenv("EASYTRADER_REPO_PATH", "").strip()

    # 1. Explicit / env var — trust user's choice, only verify 32-bit
    for candidate in [explicit, os.getenv("THS_EASYTRADER_PYTHON32", "").strip()]:
        if candidate and os.path.isfile(candidate):
            if _verify_python32(candidate):
                return candidate

    # 2. Collect all 32-bit Python candidates
    all_candidates: list[str] = []

    # From registry
    reg_found = _scan_registry_for_python32_all()
    all_candidates.extend(reg_found)

    # From common paths
    import glob
    username = os.getenv("USERNAME", os.getenv("USER", "*"))
    for pattern in _PYTHON32_SCAN_PATTERNS:
        expanded = pattern.replace("{user}", username)
        for match in sorted(glob.glob(expanded), reverse=True):
            if os.path.isfile(match) and match not in all_candidates:
                all_candidates.append(match)

    # 3. Among candidates, prefer one where easytrader works
    verified_32bit: list[str] = []
    for candidate in all_candidates:
        if _verify_python32(candidate):
            verified_32bit.append(candidate)

    # Try easytrader availability on each (most capable first)
    for candidate in verified_32bit:
        if _verify_easytrader_available(candidate, easytrader_repo):
            logger.info("[bridge] 发现可用的 32 位 Python (easytrader OK): %s", candidate)
            return candidate

    # Fallback: return any 32-bit Python (bridge worker will handle import)
    if verified_32bit:
        logger.warning("[bridge] 找到 32 位 Python 但 easytrader 未验证通过: %s", verified_32bit[0])
        return verified_32bit[0]

    return None


def _verify_python32(exe: str) -> bool:
    """Verify that the given Python executable is 32-bit."""
    try:
        result = subprocess.run(
            [exe, "-c", "import sys; print(64 if sys.maxsize > 2**32 else 32)"],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip() == "32"
    except Exception:
        return False


def _verify_easytrader_available(exe: str, easytrader_repo: str = "") -> bool:
    """Verify that easytrader can be imported AND used in the given Python.

    Tests up to easytrader.use('ths') which triggers all dependency imports
    (pandas, easyutils, etc.).
    """
    script = (
        "import sys, os\n"
        "repo = os.environ.get('EASYTRADER_REPO_PATH', '')\n"
        "if repo and os.path.isdir(repo) and repo not in sys.path:\n"
        "    sys.path.insert(0, repo)\n"
        "for rel in ['../easytrader-master', 'easytrader-master']:\n"
        "    p = os.path.normpath(os.path.join(os.getcwd(), rel))\n"
        "    if os.path.isdir(p) and p not in sys.path:\n"
        "        sys.path.insert(0, p)\n"
        "import easytrader\n"
        "easytrader.use('ths')\n"
        "print('ok')\n"
    )
    try:
        env = os.environ.copy()
        if easytrader_repo:
            env["EASYTRADER_REPO_PATH"] = easytrader_repo
        result = subprocess.run(
            [exe, "-c", script],
            capture_output=True, text=True, timeout=15, env=env,
            cwd=str(Path(__file__).resolve().parents[3]),
        )
        return "ok" in result.stdout
    except Exception:
        return False


def _scan_registry_for_python32_all() -> list[str]:
    """Scan Windows registry for 32-bit Python installations. Returns all found."""
    try:
        import winreg
    except ImportError:
        return []

    results: list[tuple[str, str]] = []  # (version, path)
    for hive in [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]:
        for base_key in [
            r"Software\Python\PythonCore",
            r"Software\WOW6432Node\Python\PythonCore",
        ]:
            try:
                key = winreg.OpenKey(hive, base_key)
            except OSError:
                continue
            try:
                i = 0
                while True:
                    try:
                        version = winreg.EnumKey(key, i)
                        i += 1
                    except OSError:
                        break
                    # Check if this is a 32-bit installation
                    for sub in [f"{version}-32\\InstallPath", f"{version}\\InstallPath"]:
                        try:
                            sub_key = winreg.OpenKey(hive, f"{base_key}\\{sub}")
                            install_path, _ = winreg.QueryValueEx(sub_key, "")
                            winreg.CloseKey(sub_key)
                            exe = os.path.join(install_path, "python.exe")
                            if os.path.isfile(exe):
                                results.append((version, exe))
                        except OSError:
                            continue
            finally:
                winreg.CloseKey(key)

    # Return sorted by version descending (prefer newer), deduplicated
    seen: set[str] = set()
    out: list[str] = []
    for _ver, exe in sorted(results, reverse=True):
        norm = os.path.normcase(exe)
        if norm not in seen:
            seen.add(norm)
            out.append(exe)
    return out


class BridgeProxyClient:
    """Drop-in proxy for easytrader client that delegates to a 32-bit subprocess.

    Implements the same interface that THSBroker expects:
    - Properties: balance, position, today_entrusts, today_trades
    - Methods: buy(), sell(), cancel_entrust(), exit(), connect()
    """

    def __init__(self, python32_exe: str, easytrader_repo: str = ""):
        self._python32 = python32_exe
        self._easytrader_repo = easytrader_repo
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._msg_id = 0
        self._connected = False

    def _start_worker(self) -> None:
        """Launch the 32-bit bridge worker subprocess."""
        if self._proc is not None and self._proc.poll() is None:
            return

        env = os.environ.copy()
        if self._easytrader_repo:
            env["EASYTRADER_REPO_PATH"] = self._easytrader_repo
        # Force UTF-8 encoding for stdin/stdout in the subprocess
        env["PYTHONIOENCODING"] = "utf-8"

        worker_script = str(_BRIDGE_WORKER)
        logger.info("[bridge] starting 32-bit worker: %s %s", self._python32, worker_script)

        self._proc = subprocess.Popen(
            [self._python32, worker_script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=env,
            cwd=str(Path(__file__).resolve().parents[3]),  # project root
        )

        # Read the ready signal
        ready_line = self._proc.stdout.readline()
        if not ready_line:
            stderr_out = ""
            try:
                stderr_out = self._proc.stderr.read(2000)
            except Exception:
                pass
            raise RuntimeError(f"bridge worker failed to start. stderr: {stderr_out}")

        ready = json.loads(ready_line)
        if not ready.get("ok"):
            raise RuntimeError(f"bridge worker not ready: {ready}")

        bits = ready.get("result", {}).get("bits", "?")
        logger.info("[bridge] worker ready (pid=%s, bits=%s)", self._proc.pid, bits)

    def _call(self, method: str, params: dict | None = None, timeout: float = 120.0) -> Any:
        """Send a JSON-RPC call to the bridge worker and return the result."""
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                raise RuntimeError("bridge worker not running")

            self._msg_id += 1
            msg_id = self._msg_id
            request = {"id": msg_id, "method": method}
            if params:
                request["params"] = params

            line = json.dumps(request, ensure_ascii=False) + "\n"
            try:
                self._proc.stdin.write(line)
                self._proc.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise RuntimeError(f"bridge write failed: {exc}") from exc

            # Read response with timeout using a thread
            result_container: list[str | None] = [None]
            error_container: list[Exception | None] = [None]

            def _read():
                try:
                    result_container[0] = self._proc.stdout.readline()
                except Exception as exc:
                    error_container[0] = exc

            reader = threading.Thread(target=_read, daemon=True)
            reader.start()
            reader.join(timeout=timeout)

            if reader.is_alive():
                raise TimeoutError(f"bridge call '{method}' timed out after {timeout}s")

            if error_container[0] is not None:
                raise RuntimeError(f"bridge read failed: {error_container[0]}")

            resp_line = result_container[0]
            if not resp_line:
                stderr_out = ""
                try:
                    stderr_out = self._proc.stderr.read(2000)
                except Exception:
                    pass
                raise RuntimeError(f"bridge returned empty response for '{method}'. stderr: {stderr_out}")

            resp = json.loads(resp_line)
            if resp.get("id") != msg_id:
                logger.warning("[bridge] response id mismatch: expected=%s got=%s", msg_id, resp.get("id"))

            if not resp.get("ok"):
                raise RuntimeError(f"bridge call '{method}' failed: {resp.get('error', 'unknown')}")

            return resp.get("result")

    def connect(self, *, exe_path: str = "", **kwargs) -> None:
        """Connect to THS via the 32-bit bridge."""
        self._start_worker()
        self._call("connect", {
            "exe_path": exe_path,
            "broker": kwargs.get("broker", "ths"),
            "grid_strategy": kwargs.get("grid_strategy", ""),
            "captcha_engine": kwargs.get("captcha_engine", ""),
        }, timeout=60.0)
        self._connected = True

    @property
    def balance(self):
        return self._call("get_balance")

    @property
    def position(self):
        return self._call("get_position")

    @property
    def today_entrusts(self):
        return self._call("get_today_entrusts")

    @property
    def today_trades(self):
        return self._call("get_today_trades")

    def buy(self, ticker: str, price: float = 0, amount: int = 0, **kwargs) -> Any:
        return self._call("buy", {"ticker": ticker, "price": price, "quantity": amount or kwargs.get("quantity", 0)})

    def sell(self, ticker: str, price: float = 0, amount: int = 0, **kwargs) -> Any:
        return self._call("sell", {"ticker": ticker, "price": price, "quantity": amount or kwargs.get("quantity", 0)})

    def cancel_entrust(self, entrust_no: str) -> Any:
        return self._call("cancel_entrust", {"entrust_no": entrust_no})

    def exit(self) -> None:
        try:
            if self._proc and self._proc.poll() is None:
                self._call("shutdown", timeout=5.0)
        except Exception:
            pass
        self._cleanup()

    def _cleanup(self) -> None:
        proc = self._proc
        self._proc = None
        self._connected = False
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
        except Exception:
            pass

    def __del__(self):
        self._cleanup()
