from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_THS_ROOT = Path(r"D:\同花顺软件\同花顺")


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_python() -> str:
    candidates = [
        PROJECT_ROOT / ".venv" / "Scripts" / "python.exe",
        PROJECT_ROOT / ".venv" / "Scripts" / "python",
    ]
    for item in candidates:
        if item.exists():
            return str(item)
    return sys.executable


def _default_report_path() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return PROJECT_ROOT / "data" / "smoke" / "reports" / f"ths_host_autostart_flow_{stamp}.json"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="One-click THS host autostart install + runtime probe + mode gate.")
    parser.add_argument("--mode", choices=["paper", "real"], default="paper")
    parser.add_argument("--ths-root", default=str(DEFAULT_THS_ROOT))
    parser.add_argument("--no-install", action="store_true")
    parser.add_argument("--start-xiadan-if-missing", action="store_true")
    parser.add_argument("--xiadan-wait-seconds", type=float, default=30.0)
    parser.add_argument("--probe-timeout-seconds", type=float, default=60.0)
    parser.add_argument("--require-snapshot", action="store_true")
    parser.add_argument("--no-easytrader-diag", action="store_true")
    parser.add_argument("--easytrader-repo", default="")
    parser.add_argument("--easytrader-broker", default="ths")
    parser.add_argument("--easytrader-exe-path", default="")
    parser.add_argument("--easytrader-include-trades", action="store_true")
    parser.add_argument("--easytrader-no-runtime-guard", action="store_true")
    parser.add_argument("--easytrader-allow-64bit-python", action="store_true")
    parser.add_argument("--easytrader-no-require-process-access", action="store_true")
    parser.add_argument("--skip-mode-gate", action="store_true")
    parser.add_argument("--report-output", default=str(_default_report_path()))
    return parser.parse_args()


def _resolve_path(path_like: str) -> Path:
    path = Path(path_like).expanduser()
    if path.is_absolute():
        return path
    return (PROJECT_ROOT / path).resolve()


def _run(cmd: list[str]) -> dict[str, Any]:
    proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT), check=False)
    return {
        "command": cmd,
        "returncode": proc.returncode,
    }


def _is_process_running(name: str) -> tuple[bool | None, str]:
    proc = subprocess.run(
        ["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV", "/NH"],
        capture_output=True,
        check=False,
        text=True,
        encoding="gbk",
        errors="ignore",
    )
    text = f"{proc.stdout}\n{proc.stderr}".strip().lower()
    if "access denied" in text:
        return None, "access_denied"
    if "no tasks are running" in text:
        return False, ""
    if name.lower() in text:
        return True, ""
    if proc.returncode != 0:
        return None, text.strip() or f"tasklist_rc={proc.returncode}"
    return False, ""


def _start_xiadan(ths_root: Path) -> tuple[bool, str]:
    exe = ths_root / "xiadan.exe"
    if not exe.exists():
        return False, f"xiadan.exe not found: {exe}"
    try:
        subprocess.Popen([str(exe)], cwd=str(ths_root))
        return True, "started"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _wait_xiadan_running(timeout_s: float) -> bool:
    deadline = time.time() + max(1.0, float(timeout_s))
    while time.time() < deadline:
        running, _ = _is_process_running("xiadan.exe")
        if running:
            return True
        time.sleep(0.5)
    running, _ = _is_process_running("xiadan.exe")
    return bool(running)


def main() -> int:
    args = _parse_args()
    python_exec = _resolve_python()
    report_output = _resolve_path(args.report_output)
    report_output.parent.mkdir(parents=True, exist_ok=True)
    ths_root = _resolve_path(args.ths_root)

    install_report = PROJECT_ROOT / "data" / "smoke" / "reports" / "ths_host_autostart_install_latest.json"
    probe_report = PROJECT_ROOT / "data" / "smoke" / "reports" / "ths_host_runtime_probe_latest.json"
    gate_report = PROJECT_ROOT / "data" / "smoke" / "reports" / f"oneclick_ths_{args.mode}_host_latest.json"
    gate_matrix = PROJECT_ROOT / "data" / "smoke" / "reports" / f"matrix_ths_{args.mode}_host_latest.json"

    report: dict[str, Any] = {
        "report_version": "1.1",
        "started_at": _iso_now(),
        "finished_at": "",
        "inputs": {
            "mode": args.mode,
            "ths_root": str(ths_root),
            "install_enabled": not args.no_install,
            "start_xiadan_if_missing": bool(args.start_xiadan_if_missing),
            "xiadan_wait_seconds": float(args.xiadan_wait_seconds),
            "probe_timeout_seconds": float(args.probe_timeout_seconds),
            "require_snapshot": bool(args.require_snapshot),
            "enable_easytrader_diag": not bool(args.no_easytrader_diag),
            "easytrader_repo": str(args.easytrader_repo or ""),
            "easytrader_broker": str(args.easytrader_broker or "ths"),
            "easytrader_exe_path": str(args.easytrader_exe_path or ""),
            "easytrader_include_trades": bool(args.easytrader_include_trades),
            "easytrader_runtime_guard": not bool(args.easytrader_no_runtime_guard),
            "easytrader_require_32bit_python": not bool(args.easytrader_allow_64bit_python),
            "easytrader_require_process_access": not bool(args.easytrader_no_require_process_access),
            "skip_mode_gate": bool(args.skip_mode_gate),
        },
        "artifacts": {
            "install_report": str(install_report),
            "probe_report": str(probe_report),
            "gate_report": str(gate_report),
            "gate_matrix": str(gate_matrix),
        },
        "steps": [],
        "ok": False,
    }

    xiadan_running, xiadan_check_error = _is_process_running("xiadan.exe")
    report["steps"].append(
        {
            "name": "check_xiadan_process",
            "xiadan_running": xiadan_running,
            "check_error": xiadan_check_error,
        }
    )
    if args.start_xiadan_if_missing and xiadan_running is False:
        ok, message = _start_xiadan(ths_root)
        report["steps"].append(
            {
                "name": "start_xiadan_if_missing",
                "ok": ok,
                "message": message,
                "xiadan_running_before": False,
            }
        )
        if ok:
            xiadan_running = _wait_xiadan_running(args.xiadan_wait_seconds)
        report["steps"][-1]["xiadan_running_after"] = xiadan_running
    elif args.start_xiadan_if_missing and xiadan_running is None:
        report["steps"].append(
            {
                "name": "start_xiadan_if_missing",
                "skipped": True,
                "message": "process_check_unavailable",
            }
        )

    if not args.no_install:
        install_cmd = [
            python_exec,
            str(PROJECT_ROOT / "scripts" / "ths" / "install_host_autostart.py"),
            "--ths-root",
            str(ths_root),
            "--report-output",
            str(install_report),
        ]
        report["steps"].append({"name": "install_host_autostart", **_run(install_cmd)})
        if report["steps"][-1]["returncode"] != 0:
            report["finished_at"] = _iso_now()
            report_output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[ths-host-flow] report={report_output}")
            print("[ths-host-flow] install failed.")
            return 2

    probe_cmd = [
        python_exec,
        str(PROJECT_ROOT / "scripts" / "ths" / "run_host_runtime_probe.py"),
        "--ths-root",
        str(ths_root),
        "--timeout-seconds",
        str(args.probe_timeout_seconds),
        "--report-output",
        str(probe_report),
    ]
    if args.require_snapshot:
        probe_cmd.append("--require-snapshot")
    if args.no_easytrader_diag:
        probe_cmd.append("--no-easytrader-diag")
    if args.easytrader_repo:
        probe_cmd.extend(["--easytrader-repo", str(args.easytrader_repo)])
    if args.easytrader_broker:
        probe_cmd.extend(["--easytrader-broker", str(args.easytrader_broker)])
    if args.easytrader_exe_path:
        probe_cmd.extend(["--easytrader-exe-path", str(args.easytrader_exe_path)])
    if args.easytrader_include_trades:
        probe_cmd.append("--easytrader-include-trades")
    if args.easytrader_no_runtime_guard:
        probe_cmd.append("--easytrader-no-runtime-guard")
    if args.easytrader_allow_64bit_python:
        probe_cmd.append("--easytrader-allow-64bit-python")
    if args.easytrader_no_require_process_access:
        probe_cmd.append("--easytrader-no-require-process-access")

    report["steps"].append({"name": "probe_host_runtime", **_run(probe_cmd)})
    if report["steps"][-1]["returncode"] != 0:
        report["finished_at"] = _iso_now()
        report_output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[ths-host-flow] report={report_output}")
        print("[ths-host-flow] runtime probe failed.")
        return 2

    if not args.skip_mode_gate:
        gate_cmd = [
            python_exec,
            str(PROJECT_ROOT / "scripts" / "smoke" / "run_ths_mode_gate.py"),
            "--mode",
            args.mode,
            "--host-runtime-only",
            "--matrix-output",
            str(gate_matrix),
            "--report-output",
            str(gate_report),
        ]
        report["steps"].append({"name": "run_ths_mode_gate", **_run(gate_cmd)})
        final_code = int(report["steps"][-1]["returncode"])
    else:
        report["steps"].append({"name": "run_ths_mode_gate", "skipped": True, "returncode": 0})
        final_code = 0

    report["ok"] = final_code == 0
    report["finished_at"] = _iso_now()
    report_output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[ths-host-flow] report={report_output}")
    print(f"[ths-host-flow] ok={report['ok']}")
    return final_code


if __name__ == "__main__":
    raise SystemExit(main())
