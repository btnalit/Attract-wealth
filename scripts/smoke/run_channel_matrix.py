from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_SMOKE_CHANNELS = "ths_ipc,simulation"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run smoke checks for multiple channels.")
    parser.add_argument(
        "--channels",
        default=os.getenv("SMOKE_DEFAULT_CHANNELS", DEFAULT_SMOKE_CHANNELS),
        help="Comma-separated channels.",
    )
    parser.add_argument("--include-order-probe", action="store_true")
    parser.add_argument("--force-live-order", action="store_true")
    parser.add_argument("--include-reconcile", action="store_true")
    parser.add_argument("--strict-preflight", action="store_true")
    parser.add_argument("--allow-skip", action="store_true", default=True)
    parser.add_argument("--disallow-skip", action="store_true", help="Treat SKIP as failure.")
    parser.add_argument("--with-stability-probe", action="store_true")
    parser.add_argument("--with-budget-recovery-probe", action="store_true")
    parser.add_argument("--no-budget-recovery-probe", action="store_true")
    parser.add_argument("--probe-iterations", type=int, default=80)
    parser.add_argument("--probe-failure-every", type=int, default=9)
    parser.add_argument("--probe-rate-limit-per-minute", type=int, default=90)
    parser.add_argument("--probe-max-wait-ms", type=int, default=0)
    parser.add_argument("--probe-retry-count", type=int, default=2)
    parser.add_argument("--probe-retry-base-ms", type=int, default=30)
    parser.add_argument("--probe-fail-on-quality", choices=["none", "warn", "critical"], default="critical")
    parser.add_argument("--budget-probe-cycles", type=int, default=20)
    parser.add_argument("--budget-probe-active-steps", type=int, default=2)
    parser.add_argument("--budget-probe-recovery-steps", type=int, default=3)
    parser.add_argument("--budget-probe-interval-ms", type=int, default=120)
    parser.add_argument("--budget-probe-budget-usd", type=float, default=1.0)
    parser.add_argument("--budget-probe-exceed-cost", type=float, default=1.2)
    parser.add_argument("--budget-probe-recover-cost", type=float, default=0.6)
    parser.add_argument("--budget-probe-recovery-ratio", type=float, default=0.8)
    parser.add_argument("--budget-probe-cooldown-s", type=float, default=0.2)
    parser.add_argument("--budget-probe-action", choices=["force_hold", "warn_only", "none"], default="force_hold")
    parser.add_argument("--budget-probe-min-success-rate", type=float, default=0.95)
    parser.add_argument("--budget-probe-max-avg-recovery-s", type=float, default=5.0)
    parser.add_argument("--output", default="", help="Aggregate report path.")
    return parser.parse_args()


def _default_output_path() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("data") / "smoke" / "reports" / f"matrix_{stamp}.json"


def _pick_python_executable() -> str:
    candidates = [
        Path(".venv") / "Scripts" / "python.exe",
        Path(".venv") / "Scripts" / "python",
    ]
    for item in candidates:
        if item.exists():
            return str(item)
    return sys.executable


def _channel_gate_ok(status: str, *, allow_skip: bool) -> bool:
    if status == "PASS":
        return True
    if status == "SKIP" and allow_skip:
        return True
    return False


def _run_channel(args: argparse.Namespace, channel: str, report_path: Path) -> dict[str, Any]:
    python_executable = _pick_python_executable()
    cmd = [
        python_executable,
        "scripts/smoke/live_channel_smoke.py",
        "--channel",
        channel,
        "--output",
        str(report_path),
    ]
    if args.include_order_probe:
        cmd.append("--include-order-probe")
    if args.force_live_order:
        cmd.append("--force-live-order")
    if args.include_reconcile:
        cmd.append("--include-reconcile")
    if args.strict_preflight:
        cmd.append("--strict-preflight")

    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    status = "FAIL"
    parsed: dict[str, Any] = {}
    if report_path.exists():
        try:
            parsed = json.loads(report_path.read_text(encoding="utf-8"))
            status = str(parsed.get("status", "FAIL")).upper()
        except Exception:  # noqa: BLE001
            status = "FAIL"

    return {
        "channel": channel,
        "status": status,
        "gate_ok": _channel_gate_ok(status, allow_skip=args.allow_skip),
        "returncode": proc.returncode,
        "report": str(report_path),
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "checks": parsed.get("checks", []),
        "preflight": parsed.get("preflight", {}),
    }


def _run_stability_probe(args: argparse.Namespace, report_path: Path) -> dict[str, Any]:
    python_executable = _pick_python_executable()
    cmd = [
        python_executable,
        "scripts/dataflow/stability_probe.py",
        "--iterations",
        str(args.probe_iterations),
        "--failure-every",
        str(args.probe_failure_every),
        "--rate-limit-per-minute",
        str(args.probe_rate_limit_per_minute),
        "--max-wait-ms",
        str(args.probe_max_wait_ms),
        "--retry-count",
        str(args.probe_retry_count),
        "--retry-base-ms",
        str(args.probe_retry_base_ms),
        "--fail-on-quality",
        str(args.probe_fail_on_quality),
        "--output",
        str(report_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)

    parsed: dict[str, Any] = {}
    status = "BLOCK"
    if report_path.exists():
        try:
            parsed = json.loads(report_path.read_text(encoding="utf-8"))
            status = str(parsed.get("gate", {}).get("status", "BLOCK")).upper()
        except Exception:  # noqa: BLE001
            status = "BLOCK"

    return {
        "enabled": True,
        "status": status,
        "gate_ok": status != "BLOCK",
        "returncode": proc.returncode,
        "report": str(report_path),
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "summary": parsed.get("summary", {}),
        "quality": parsed.get("quality", {}),
        "tuning": parsed.get("tuning", {}),
        "gate": parsed.get("gate", {}),
    }


def _run_budget_recovery_probe(args: argparse.Namespace, report_path: Path) -> dict[str, Any]:
    python_executable = _pick_python_executable()
    cmd = [
        python_executable,
        "scripts/dataflow/budget_recovery_probe.py",
        "--cycles",
        str(args.budget_probe_cycles),
        "--active-steps",
        str(args.budget_probe_active_steps),
        "--recovery-steps",
        str(args.budget_probe_recovery_steps),
        "--interval-ms",
        str(args.budget_probe_interval_ms),
        "--budget-usd",
        str(args.budget_probe_budget_usd),
        "--exceed-cost",
        str(args.budget_probe_exceed_cost),
        "--recover-cost",
        str(args.budget_probe_recover_cost),
        "--recovery-ratio",
        str(args.budget_probe_recovery_ratio),
        "--cooldown-s",
        str(args.budget_probe_cooldown_s),
        "--action",
        str(args.budget_probe_action),
        "--min-success-rate",
        str(args.budget_probe_min_success_rate),
        "--max-avg-recovery-s",
        str(args.budget_probe_max_avg_recovery_s),
        "--output",
        str(report_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)

    parsed: dict[str, Any] = {}
    status = "BLOCK"
    if report_path.exists():
        try:
            parsed = json.loads(report_path.read_text(encoding="utf-8"))
            status = str(parsed.get("gate", {}).get("status", "BLOCK")).upper()
        except Exception:  # noqa: BLE001
            status = "BLOCK"

    return {
        "enabled": True,
        "status": status,
        "gate_ok": status != "BLOCK",
        "returncode": proc.returncode,
        "report": str(report_path),
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "summary": parsed.get("summary", {}),
        "params": parsed.get("params", {}),
        "gate": parsed.get("gate", {}),
    }


def main() -> int:
    args = _parse_args()
    if args.disallow_skip:
        args.allow_skip = False
    if args.no_budget_recovery_probe:
        args.with_budget_recovery_probe = False
    channels = [item.strip() for item in args.channels.split(",") if item.strip()]
    reports_dir = Path("data") / "smoke" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    channel_rows: list[dict[str, Any]] = []
    for channel in channels:
        report_path = reports_dir / f"{channel}_latest.json"
        channel_rows.append(_run_channel(args, channel, report_path))

    stability_result: dict[str, Any] = {"enabled": False, "status": "SKIP", "gate_ok": True}
    if args.with_stability_probe:
        stability_report = reports_dir / "dataflow_stability_latest.json"
        stability_result = _run_stability_probe(args, stability_report)

    budget_recovery_result: dict[str, Any] = {"enabled": False, "status": "SKIP", "gate_ok": True}
    if args.with_budget_recovery_probe:
        budget_recovery_report = reports_dir / "budget_recovery_latest.json"
        budget_recovery_result = _run_budget_recovery_probe(args, budget_recovery_report)

    pass_count = sum(1 for item in channel_rows if item["status"] == "PASS")
    skip_count = sum(1 for item in channel_rows if item["status"] == "SKIP")
    fail_count = sum(1 for item in channel_rows if item["status"] == "FAIL")
    channels_gate_ok = all(item["gate_ok"] for item in channel_rows) if channel_rows else False
    all_passed = (
        channels_gate_ok
        and bool(stability_result.get("gate_ok", True))
        and bool(budget_recovery_result.get("gate_ok", True))
    )

    aggregate = {
        "report_version": "1.2",
        "generated_at": datetime.now().isoformat(),
        "channels": channels,
        "allow_skip": bool(args.allow_skip),
        "counts": {
            "pass": pass_count,
            "skip": skip_count,
            "fail": fail_count,
        },
        "all_passed": all_passed,
        "results": channel_rows,
        "stability_probe": stability_result,
        "budget_recovery_probe": budget_recovery_result,
    }

    output_path = Path(args.output).expanduser() if args.output else _default_output_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(aggregate, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[smoke-matrix] output={output_path} all_passed={aggregate['all_passed']}")
    return 0 if aggregate["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
