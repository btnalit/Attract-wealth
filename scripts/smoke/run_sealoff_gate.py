from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SEALOFF_PROFILE = "ths_sim_strict"


@dataclass(frozen=True)
class SealoffProfile:
    name: str
    description: str
    channels: str
    include_order_probe: bool
    force_live_order: bool
    include_reconcile: bool
    with_stability_probe: bool
    with_budget_recovery_probe: bool = True
    probe_iterations: int = 80
    probe_failure_every: int = 4
    probe_rate_limit_per_minute: int = 90
    probe_max_wait_ms: int = 0
    probe_retry_count: int = 2
    probe_retry_base_ms: int = 30
    probe_fail_on_quality: str = "critical"
    budget_probe_cycles: int = 20
    budget_probe_active_steps: int = 2
    budget_probe_recovery_steps: int = 3
    budget_probe_interval_ms: int = 120
    budget_probe_budget_usd: float = 1.0
    budget_probe_exceed_cost: float = 1.2
    budget_probe_recover_cost: float = 0.6
    budget_probe_recovery_ratio: float = 0.8
    budget_probe_cooldown_s: float = 0.2
    budget_probe_action: str = "force_hold"
    budget_probe_min_success_rate: float = 0.95
    budget_probe_max_avg_recovery_s: float = 5.0
    require_allow_live_order: bool = False


P2_B3_BASELINE_ENV: dict[str, str] = {
    "DATA_PROVIDER_RATE_LIMIT_PER_MINUTE": "120",
    "DATA_PROVIDER_MIN_INTERVAL_MS": "120",
    "DATA_PROVIDER_MAX_WAIT_MS": "400",
    "DATA_PROVIDER_BACKOFF_RETRIES": "2",
    "DATA_PROVIDER_BACKOFF_BASE_MS": "80",
    "DATA_PROVIDER_BACKOFF_FACTOR": "2.0",
    "DATA_PROVIDER_BACKOFF_MAX_MS": "1000",
    "DATA_QUALITY_ERROR_WARN": "0.15",
    "DATA_QUALITY_ERROR_BLOCK": "0.40",
    "DATA_QUALITY_EMPTY_WARN": "0.30",
    "DATA_QUALITY_EMPTY_BLOCK": "0.70",
    "DATA_QUALITY_RETRY_WARN": "0.20",
    "DATA_QUALITY_RETRY_BLOCK": "0.60",
    "DATA_QUALITY_RATE_LIMIT_WARN": "0.20",
    "DATA_QUALITY_RATE_LIMIT_BLOCK": "0.50",
    "DATA_QUALITY_STALE_WARN_DAYS": "3",
    "DATA_QUALITY_STALE_BLOCK_DAYS": "7",
    "DATA_QUALITY_PROVIDER_ERROR_WARN": "0.50",
    "DATA_QUALITY_PROVIDER_ERROR_BLOCK": "0.90",
    "DATA_QUALITY_PROVIDER_MIN_REQUESTS": "3",
}


PROFILES: dict[str, SealoffProfile] = {
    "ths_real_probe": SealoffProfile(
        name="ths_real_probe",
        description="同花顺真实账户连通 + 下单探针（不跑对账和稳定性压测）",
        channels="ths_ipc",
        include_order_probe=True,
        force_live_order=True,
        include_reconcile=False,
        with_stability_probe=False,
        with_budget_recovery_probe=False,
        require_allow_live_order=True,
    ),
    "ths_paper_full": SealoffProfile(
        name="ths_paper_full",
        description="同花顺模拟盘完整链路（order_probe + reconcile + stability_probe）",
        channels="ths_ipc",
        include_order_probe=True,
        force_live_order=True,
        include_reconcile=True,
        with_stability_probe=True,
        require_allow_live_order=True,
    ),
    "ths_sim_strict": SealoffProfile(
        name="ths_sim_strict",
        description="本机主线封板（ths_ipc + simulation + reconcile + stability_probe）",
        channels="ths_ipc,simulation",
        include_order_probe=False,
        force_live_order=False,
        include_reconcile=True,
        with_stability_probe=True,
    ),
    "ths_sim_probe": SealoffProfile(
        name="ths_sim_probe",
        description="本机全探针封板（ths_ipc + simulation + order_probe + reconcile + stability_probe）",
        channels="ths_ipc,simulation",
        include_order_probe=True,
        force_live_order=True,
        include_reconcile=True,
        with_stability_probe=True,
        require_allow_live_order=True,
    ),
    "dual_channel_strict": SealoffProfile(
        name="dual_channel_strict",
        description="双通道严格封板（ths_ipc,qmt + reconcile + stability_probe）",
        channels="ths_ipc,qmt",
        include_order_probe=False,
        force_live_order=False,
        include_reconcile=True,
        with_stability_probe=True,
    ),
    "simulation_strict": SealoffProfile(
        name="simulation_strict",
        description="simulation only strict sealoff for CI and no live bridge env",
        channels="simulation",
        include_order_probe=False,
        force_live_order=False,
        include_reconcile=False,
        with_stability_probe=True,
    ),
}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_path(path_like: str) -> Path:
    path = Path(path_like)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _resolve_python_executable(explicit: str) -> str:
    if explicit:
        return explicit
    candidates = [
        PROJECT_ROOT / ".venv" / "Scripts" / "python.exe",
        PROJECT_ROOT / ".venv" / "Scripts" / "python",
    ]
    for item in candidates:
        if item.exists():
            return str(item)
    return sys.executable


def _default_matrix_report(profile_name: str) -> Path:
    return PROJECT_ROOT / "data" / "smoke" / "reports" / f"matrix_sealoff_{profile_name}_latest.json"


def _default_oneclick_report(profile_name: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return PROJECT_ROOT / "data" / "smoke" / "reports" / f"oneclick_sealoff_{profile_name}_{stamp}.json"


def _default_sealoff_report(profile_name: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return PROJECT_ROOT / "data" / "smoke" / "reports" / f"sealoff_{profile_name}_{stamp}.json"


def _apply_p2b3_baseline_env() -> dict[str, str]:
    applied: dict[str, str] = {}
    for key, value in P2_B3_BASELINE_ENV.items():
        os.environ[key] = value
        applied[key] = value
    return applied


def _build_oneclick_cmd(
    args: argparse.Namespace,
    profile: SealoffProfile,
    matrix_output: Path,
    oneclick_report_output: Path,
) -> list[str]:
    cmd = [
        _resolve_python_executable(args.python_executable),
        str(PROJECT_ROOT / "scripts" / "smoke" / "run_oneclick_gate.py"),
        "--channels",
        profile.channels,
        "--matrix-output",
        str(matrix_output),
        "--report-output",
        str(oneclick_report_output),
        "--env-file",
        args.env_file,
    ]

    if args.no_load_env_file:
        cmd.append("--no-load-env-file")
    if args.no_auto_start_ths_bridge:
        cmd.append("--no-auto-start-ths-bridge")
    if args.keep_bridge:
        cmd.append("--keep-bridge")
    if args.no_precheck_first:
        cmd.append("--no-precheck-first")
    if args.no_fail_fast_precheck:
        cmd.append("--no-fail-fast-precheck")

    if profile.include_order_probe:
        cmd.append("--include-order-probe")
    if profile.force_live_order:
        cmd.append("--force-live-order")
    if not profile.include_reconcile:
        cmd.append("--no-reconcile")
    if not profile.with_stability_probe:
        cmd.append("--no-stability-probe")
    else:
        cmd.extend(
            [
                "--probe-iterations",
                str(profile.probe_iterations),
                "--probe-failure-every",
                str(profile.probe_failure_every),
                "--probe-rate-limit-per-minute",
                str(profile.probe_rate_limit_per_minute),
                "--probe-max-wait-ms",
                str(profile.probe_max_wait_ms),
                "--probe-retry-count",
                str(profile.probe_retry_count),
                "--probe-retry-base-ms",
                str(profile.probe_retry_base_ms),
                "--probe-fail-on-quality",
                str(profile.probe_fail_on_quality),
            ]
        )
    if not profile.with_budget_recovery_probe:
        cmd.append("--no-budget-recovery-probe")
    else:
        cmd.extend(
            [
                "--budget-probe-cycles",
                str(profile.budget_probe_cycles),
                "--budget-probe-active-steps",
                str(profile.budget_probe_active_steps),
                "--budget-probe-recovery-steps",
                str(profile.budget_probe_recovery_steps),
                "--budget-probe-interval-ms",
                str(profile.budget_probe_interval_ms),
                "--budget-probe-budget-usd",
                str(profile.budget_probe_budget_usd),
                "--budget-probe-exceed-cost",
                str(profile.budget_probe_exceed_cost),
                "--budget-probe-recover-cost",
                str(profile.budget_probe_recover_cost),
                "--budget-probe-recovery-ratio",
                str(profile.budget_probe_recovery_ratio),
                "--budget-probe-cooldown-s",
                str(profile.budget_probe_cooldown_s),
                "--budget-probe-action",
                str(profile.budget_probe_action),
                "--budget-probe-min-success-rate",
                str(profile.budget_probe_min_success_rate),
                "--budget-probe-max-avg-recovery-s",
                str(profile.budget_probe_max_avg_recovery_s),
            ]
        )
    return cmd


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sealoff runner for P1-H2 + P2-B3: fixed profile + fixed baseline + one-click execution."
    )
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILES.keys()),
        default=os.getenv("SEALOFF_DEFAULT_PROFILE", DEFAULT_SEALOFF_PROFILE),
    )
    parser.add_argument("--allow-live-order", action="store_true")
    parser.add_argument("--apply-p2b3-baseline", action="store_true", default=True)
    parser.add_argument("--no-apply-p2b3-baseline", action="store_true")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--no-load-env-file", action="store_true")
    parser.add_argument("--no-auto-start-ths-bridge", action="store_true")
    parser.add_argument("--keep-bridge", action="store_true")
    parser.add_argument("--no-precheck-first", action="store_true")
    parser.add_argument("--no-fail-fast-precheck", action="store_true")
    parser.add_argument("--python-executable", default="")
    parser.add_argument("--matrix-output", default="")
    parser.add_argument("--oneclick-report-output", default="")
    parser.add_argument("--sealoff-report-output", default="")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.no_apply_p2b3_baseline:
        args.apply_p2b3_baseline = False

    profile = PROFILES[args.profile]
    if profile.require_allow_live_order and not args.allow_live_order:
        print(
            f"[sealoff] profile={profile.name} requires --allow-live-order "
            "(safety gate for real/paper order probe)."
        )
        return 2

    matrix_output = _resolve_path(args.matrix_output) if args.matrix_output else _default_matrix_report(profile.name)
    oneclick_output = (
        _resolve_path(args.oneclick_report_output)
        if args.oneclick_report_output
        else _default_oneclick_report(profile.name)
    )
    sealoff_output = (
        _resolve_path(args.sealoff_report_output) if args.sealoff_report_output else _default_sealoff_report(profile.name)
    )
    matrix_output.parent.mkdir(parents=True, exist_ok=True)
    oneclick_output.parent.mkdir(parents=True, exist_ok=True)
    sealoff_output.parent.mkdir(parents=True, exist_ok=True)

    applied_env: dict[str, str] = {}
    if args.apply_p2b3_baseline:
        applied_env.update(_apply_p2b3_baseline_env())

    if profile.force_live_order and args.allow_live_order:
        os.environ["SMOKE_ALLOW_LIVE_ORDER"] = "true"
        applied_env["SMOKE_ALLOW_LIVE_ORDER"] = "true"

    cmd = _build_oneclick_cmd(args, profile, matrix_output, oneclick_output)
    started_at = _iso_now()
    returncode = 0

    print(f"[sealoff] profile={profile.name}")
    print("[sealoff] cmd:")
    print("  " + " ".join(cmd))

    if not args.dry_run:
        proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT), check=False)
        returncode = proc.returncode

    oneclick_report = _load_json(oneclick_output) if oneclick_output.exists() else {}
    gate = oneclick_report.get("gate", {}) if isinstance(oneclick_report.get("gate", {}), dict) else {}
    bridge = oneclick_report.get("bridge", {}) if isinstance(oneclick_report.get("bridge", {}), dict) else {}
    hints = gate.get("hints", [])
    if not isinstance(hints, list):
        hints = []

    result = {
        "report_version": "1.0",
        "started_at": started_at,
        "finished_at": _iso_now(),
        "dry_run": bool(args.dry_run),
        "profile": {
            "name": profile.name,
            "description": profile.description,
            "channels": profile.channels,
            "include_order_probe": profile.include_order_probe,
            "force_live_order": profile.force_live_order,
            "include_reconcile": profile.include_reconcile,
            "with_stability_probe": profile.with_stability_probe,
            "with_budget_recovery_probe": profile.with_budget_recovery_probe,
        },
        "inputs": {
            "env_file": args.env_file,
            "no_load_env_file": bool(args.no_load_env_file),
            "no_auto_start_ths_bridge": bool(args.no_auto_start_ths_bridge),
            "keep_bridge": bool(args.keep_bridge),
            "no_precheck_first": bool(args.no_precheck_first),
            "no_fail_fast_precheck": bool(args.no_fail_fast_precheck),
            "apply_p2b3_baseline": bool(args.apply_p2b3_baseline),
            "allow_live_order": bool(args.allow_live_order),
        },
        "applied_env": applied_env,
        "paths": {
            "matrix_report": str(matrix_output),
            "oneclick_report": str(oneclick_output),
            "sealoff_report": str(sealoff_output),
        },
        "command": cmd,
        "returncode": int(returncode),
        "gate_summary": {
            "all_passed": bool(gate.get("all_passed", False)),
            "bridge_ready": bool(bridge.get("ready", False)),
            "precheck_returncode": gate.get("precheck_returncode"),
            "matrix_returncode": gate.get("matrix_returncode"),
            "hints": hints,
        },
    }
    sealoff_output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[sealoff] oneclick_report={oneclick_output}")
    print(f"[sealoff] sealoff_report={sealoff_output}")
    print(
        "[sealoff] all_passed={all_passed} bridge_ready={bridge_ready} returncode={code}".format(
            all_passed=result["gate_summary"]["all_passed"],
            bridge_ready=result["gate_summary"]["bridge_ready"],
            code=returncode,
        )
    )
    if hints:
        print("[sealoff] hints:")
        for idx, hint in enumerate(hints, start=1):
            print(f"  {idx}. {hint}")

    return 0 if args.dry_run else int(returncode)


if __name__ == "__main__":
    raise SystemExit(main())
