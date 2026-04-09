from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _resolve_python() -> str:
    candidates = [
        PROJECT_ROOT / ".venv" / "Scripts" / "python.exe",
        PROJECT_ROOT / ".venv" / "Scripts" / "python",
    ]
    for item in candidates:
        if item.exists():
            return str(item)
    return sys.executable


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run THS one-click gate for a specific account mode.")
    parser.add_argument("--mode", choices=["real", "paper"], required=True, help="THS account mode tag.")
    parser.add_argument("--include-order-probe", action="store_true", default=True)
    parser.add_argument("--no-order-probe", action="store_true")
    parser.add_argument("--force-live-order", action="store_true", default=True)
    parser.add_argument("--no-force-live-order", action="store_true")
    parser.add_argument("--include-reconcile", action="store_true", default=False)
    parser.add_argument("--with-stability-probe", action="store_true", default=False)
    parser.add_argument("--keep-bridge", action="store_true")
    parser.add_argument(
        "--host-runtime-only",
        action="store_true",
        help="Require THS host runtime and disable external bridge auto-start.",
    )
    parser.add_argument(
        "--allow-external-bridge",
        action="store_true",
        help="Allow oneclick gate to auto-start external bridge process.",
    )
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--no-load-env-file", action="store_true")
    parser.add_argument("--matrix-output", default="")
    parser.add_argument("--report-output", default="")
    return parser.parse_args()


def _default_paths(mode: str) -> tuple[Path, Path]:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    matrix = PROJECT_ROOT / "data" / "smoke" / "reports" / f"matrix_ths_{mode}_latest.json"
    report = PROJECT_ROOT / "data" / "smoke" / "reports" / f"oneclick_ths_{mode}_{stamp}.json"
    return matrix, report


def main() -> int:
    args = _parse_args()
    if args.no_order_probe:
        args.include_order_probe = False
    if args.no_force_live_order:
        args.force_live_order = False
    host_runtime_only = bool(args.host_runtime_only and not args.allow_external_bridge)

    default_matrix, default_report = _default_paths(args.mode)
    matrix_output = Path(args.matrix_output).expanduser() if args.matrix_output else default_matrix
    report_output = Path(args.report_output).expanduser() if args.report_output else default_report
    matrix_output.parent.mkdir(parents=True, exist_ok=True)
    report_output.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        _resolve_python(),
        str(PROJECT_ROOT / "scripts" / "smoke" / "run_oneclick_gate.py"),
        "--channels",
        "ths_ipc",
        "--matrix-output",
        str(matrix_output),
        "--report-output",
        str(report_output),
        "--env-file",
        args.env_file,
    ]
    if args.no_load_env_file:
        cmd.append("--no-load-env-file")
    if args.include_order_probe:
        cmd.append("--include-order-probe")
    if args.force_live_order:
        cmd.append("--force-live-order")
    if not args.include_reconcile:
        cmd.append("--no-reconcile")
    if not args.with_stability_probe:
        cmd.append("--no-stability-probe")
    if args.keep_bridge:
        cmd.append("--keep-bridge")
    if host_runtime_only:
        cmd.append("--no-auto-start-ths-bridge")

    print(f"[ths-mode-gate] mode={args.mode}")
    print(f"[ths-mode-gate] host_runtime_only={host_runtime_only}")
    print("[ths-mode-gate] cmd:")
    print("  " + " ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT), check=False)

    print(f"[ths-mode-gate] matrix={matrix_output}")
    print(f"[ths-mode-gate] report={report_output}")
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
