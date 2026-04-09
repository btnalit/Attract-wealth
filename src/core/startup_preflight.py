"""Unified startup preflight checks."""
from __future__ import annotations

import importlib
import json
import os
import socket
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.core.errors import TradingServiceError
from src.execution.ths_auto.easytrader_adapter import probe_easytrader_readiness

SUPPORTED_CHANNELS = {"simulation", "ths_ipc", "ths_auto", "qmt"}


@dataclass
class PreflightCheck:
    name: str
    ok: bool
    severity: str
    message: str
    hint: str = ""
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if data["metadata"] is None:
            data["metadata"] = {}
        return data


def _is_true(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _port_reachable(host: str, port: int, timeout: float = 1.0) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _probe_ths_ipc_runtime(host: str, port: int, timeout: float = 1.0) -> tuple[bool, dict[str, Any], str]:
    payload = json.dumps({"action": "ping"}, ensure_ascii=False).encode("utf-8")
    try:
        with socket.create_connection((host, port), timeout=timeout) as conn:
            conn.sendall(payload)
            chunks: list[bytes] = []
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
        if not chunks:
            return False, {}, "empty_response"
        response = json.loads(b"".join(chunks).decode("utf-8"))
        runtime = response.get("runtime", {}) if isinstance(response.get("runtime", {}), dict) else {}
        runtime_ok = bool(runtime.get("in_ths_api") or runtime.get("in_xiadan_api"))
        return runtime_ok, runtime, ""
    except Exception as exc:  # noqa: BLE001
        return False, {}, str(exc)


def _run_easytrader_diag(
    *,
    include_orders: bool,
) -> dict[str, Any]:
    exe_path = os.getenv("THS_EXE_PATH", r"D:\同花顺软件\同花顺\xiadan.exe").strip()
    repo_path = os.getenv("EASYTRADER_REPO_PATH", "").strip()
    broker = os.getenv("THS_EASYTRADER_BROKER", "ths").strip() or "ths"
    runtime_guard = _is_true(os.getenv("THS_EASYTRADER_RUNTIME_GUARD"), default=True)
    require_32bit = _is_true(os.getenv("THS_EASYTRADER_REQUIRE_32BIT"), default=True)
    require_access = _is_true(os.getenv("THS_EASYTRADER_REQUIRE_PROCESS_ACCESS"), default=True)
    return probe_easytrader_readiness(
        exe_path=exe_path,
        broker=broker,
        repo_path=repo_path,
        include_orders=include_orders,
        runtime_guard=runtime_guard,
        require_32bit_python=require_32bit,
        require_process_access=require_access,
    )


def run_startup_preflight(
    *,
    channel: str | None = None,
    include_stability_probe: bool = False,
) -> dict[str, Any]:
    selected = (channel or os.getenv("TRADING_CHANNEL", "simulation")).strip().lower()
    checks: list[PreflightCheck] = []

    checks.append(
        PreflightCheck(
            name="trading_channel_supported",
            ok=selected in SUPPORTED_CHANNELS,
            severity="critical",
            message=f"TRADING_CHANNEL={selected}",
            hint=f"Supported channels: {', '.join(sorted(SUPPORTED_CHANNELS))}",
        )
    )

    project_root = Path(__file__).resolve().parents[2]
    data_dir = Path(os.getenv("DATA_DIR", str(project_root / "data")))
    data_dir_ok = True
    data_dir_error = ""
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:  # noqa: BLE001
        data_dir_ok = False
        data_dir_error = str(exc)
    checks.append(
        PreflightCheck(
            name="data_dir_writable",
            ok=data_dir_ok,
            severity="critical",
            message=f"DATA_DIR={data_dir}" if data_dir_ok else f"DATA_DIR not writable: {data_dir_error}",
            hint="Ensure runtime account has read/write access to DATA_DIR.",
            metadata={"path": str(data_dir)},
        )
    )

    if selected == "qmt":
        account_id = os.getenv("QMT_ACCOUNT_ID", "").strip() or os.getenv("QMT_ACCOUNT", "").strip()
        qmt_path = os.getenv("QMT_PATH", "").strip()
        qmt_path_exists = bool(qmt_path and Path(qmt_path).exists())
        try:
            from src.execution.qmt_broker import XT_AVAILABLE

            xt_ok = bool(XT_AVAILABLE)
        except Exception:
            xt_ok = False

        checks.extend(
            [
                PreflightCheck(
                    name="qmt_account",
                    ok=bool(account_id),
                    severity="critical",
                    message="QMT account configured" if account_id else "missing QMT_ACCOUNT_ID/QMT_ACCOUNT",
                    hint="Set QMT_ACCOUNT_ID (or legacy QMT_ACCOUNT).",
                ),
                PreflightCheck(
                    name="qmt_path",
                    ok=qmt_path_exists,
                    severity="critical",
                    message=f"QMT_PATH={qmt_path}" if qmt_path else "missing QMT_PATH",
                    hint="Set QMT_PATH to miniQMT data directory.",
                ),
                PreflightCheck(
                    name="xtquant_module",
                    ok=xt_ok,
                    severity="critical",
                    message="xtquant import ok" if xt_ok else "xtquant import failed",
                    hint="Install broker-provided xtquant package in current interpreter.",
                ),
            ]
        )

    if selected == "ths_ipc":
        host = os.getenv("THS_IPC_HOST", "127.0.0.1").strip() or "127.0.0.1"
        port = int(os.getenv("THS_IPC_PORT", "8089"))
        reachable, err = _port_reachable(host, port)
        checks.append(
            PreflightCheck(
                name="ths_ipc_bridge",
                ok=reachable,
                severity="critical",
                message=f"{host}:{port} reachable" if reachable else f"{host}:{port} unreachable: {err}",
                hint="Load THS host script and ensure bridge listens on THS_IPC_PORT.",
                metadata={"host": host, "port": port},
            )
        )

        require_runtime = _is_true(os.getenv("THS_IPC_REQUIRE_RUNTIME"), default=True)
        allow_mock = _is_true(os.getenv("THS_IPC_ALLOW_MOCK"), default=False)
        runtime_ok = True
        runtime_meta: dict[str, Any] = {}
        runtime_err = ""
        if reachable and require_runtime and not allow_mock:
            runtime_ok, runtime_meta, runtime_err = _probe_ths_ipc_runtime(host, port)
            checks.append(
                PreflightCheck(
                    name="ths_ipc_runtime",
                    ok=runtime_ok,
                    severity="critical",
                    message="runtime is THS host" if runtime_ok else f"invalid runtime: {runtime_err or 'mock_runtime'}",
                    hint=(
                        "Bridge must run in THS host runtime "
                        "(in_ths_api/in_xiadan_api at least one true). "
                        "For local mock debugging only, set THS_IPC_ALLOW_MOCK=true."
                    ),
                    metadata={"runtime": runtime_meta},
                )
            )

        enable_diag = _is_true(os.getenv("THS_IPC_ENABLE_EASYTRADER_DIAG"), default=True)
        should_run_diag = enable_diag and (not reachable or not runtime_ok)
        if should_run_diag:
            diag = _run_easytrader_diag(include_orders=False)
            diag_ok = bool(diag.get("ok", False))
            checks.append(
                PreflightCheck(
                    name="ths_easytrader_diag",
                    ok=diag_ok,
                    severity="warning",
                    message=(
                        "easytrader can read THS account snapshot"
                        if diag_ok
                        else "easytrader snapshot probe failed"
                    ),
                    hint=(
                        "If this check passes but ths_ipc fails, the usual cause is host script not loaded. "
                        "Open THS signal strategy page once to trigger my_signals.py."
                    ),
                    metadata={
                        "summary": diag.get("summary", {}),
                        "errors": diag.get("errors", []),
                        "meta": diag.get("meta", {}),
                    },
                )
            )

    if selected == "ths_auto":
        exe_path = os.getenv("THS_EXE_PATH", r"D:\同花顺软件\同花顺\xiadan.exe").strip()
        exe_exists = Path(exe_path).exists()
        allow_stub = _is_true(os.getenv("THS_AUTO_ALLOW_STUB"), default=False)

        checks.append(
            PreflightCheck(
                name="ths_auto_exe",
                ok=exe_exists,
                severity="critical",
                message=f"THS_EXE_PATH={exe_path}",
                hint="Set THS_EXE_PATH to xiadan.exe path.",
                metadata={"path": exe_path},
            )
        )

        easytrader_diag: dict[str, Any] = {}
        easytrader_ok = False
        if exe_exists:
            easytrader_diag = _run_easytrader_diag(include_orders=True)
            easytrader_ok = bool(easytrader_diag.get("ok", False))
            checks.append(
                PreflightCheck(
                    name="ths_auto_easytrader",
                    ok=easytrader_ok,
                    severity="critical",
                    message="easytrader connected and snapshot readable"
                    if easytrader_ok
                    else "easytrader connect/snapshot failed",
                    hint="Check logged xiadan session, easytrader dependencies and process desktop session.",
                    metadata={
                        "summary": easytrader_diag.get("summary", {}),
                        "errors": easytrader_diag.get("errors", []),
                        "meta": easytrader_diag.get("meta", {}),
                    },
                )
            )

        checks.append(
            PreflightCheck(
                name="ths_auto_stub_policy",
                ok=allow_stub or easytrader_ok,
                severity="critical",
                message=(
                    "ths_auto real runtime ready"
                    if easytrader_ok
                    else ("THS_AUTO_ALLOW_STUB=true" if allow_stub else "ths_auto real runtime not ready")
                ),
                hint=(
                    "Use ths_ipc as primary channel; for ths_auto fallback, ensure easytrader works. "
                    "Set THS_AUTO_ALLOW_STUB=true only for non-production debugging."
                ),
                metadata={
                    "allow_stub": allow_stub,
                    "easytrader_ok": easytrader_ok,
                },
            )
        )

    if include_stability_probe:
        try:
            importlib.import_module("pandas")
            pandas_ok = True
        except Exception:
            pandas_ok = False
        checks.append(
            PreflightCheck(
                name="pandas_module",
                ok=pandas_ok,
                severity="warning",
                message="pandas import ok" if pandas_ok else "pandas import failed",
                hint="Install pandas before running stability probe scripts.",
            )
        )

    total = len(checks)
    critical_failed = [item.to_dict() for item in checks if not item.ok and item.severity == "critical"]
    warning_failed = [item.to_dict() for item in checks if not item.ok and item.severity != "critical"]
    return {
        "checked_at": _iso_now(),
        "channel": selected,
        "ok": len(critical_failed) == 0,
        "summary": {
            "total": total,
            "failed": len(critical_failed) + len(warning_failed),
            "critical_failed": len(critical_failed),
            "warning_failed": len(warning_failed),
        },
        "checks": [item.to_dict() for item in checks],
    }


def raise_for_failed_preflight(report: dict[str, Any]) -> None:
    if report.get("ok", False):
        return
    failed = [item for item in report.get("checks", []) if not item.get("ok", False)]
    raise TradingServiceError(
        code="PREFLIGHT_FAILED",
        message="startup preflight failed, fix required checks then retry.",
        details={
            "summary": report.get("summary", {}),
            "failed_checks": failed,
        },
        http_status=503,
    )



