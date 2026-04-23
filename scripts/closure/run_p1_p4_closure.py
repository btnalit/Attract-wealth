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


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_python_executable(explicit: str) -> str:
    if str(explicit or "").strip():
        return str(explicit).strip()
    candidates = [
        PROJECT_ROOT / ".venv" / "Scripts" / "python.exe",
        PROJECT_ROOT / ".venv" / "Scripts" / "python",
    ]
    for item in candidates:
        if item.exists():
            return str(item)
    return sys.executable


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="One-click P1-P4 closure runner.")
    parser.add_argument("--python-executable", default="")
    parser.add_argument("--output-dir", default="data/closure/reports")
    parser.add_argument("--output", default="", help="Closure report output path.")
    parser.add_argument("--fail-fast", action="store_true", help="Stop when one step fails.")
    parser.add_argument("--strict-mode", action="store_true", help="Enforce zero-warn strict closure settings.")
    parser.add_argument(
        "--strict-level",
        choices=["ci", "ths_live"],
        default="ths_live",
        help="ci: simulation-biased strict; ths_live: ths_ipc+simulation strict chain.",
    )

    parser.add_argument("--p1-profile", default="ths_sim_strict")
    parser.add_argument("--p1-allow-live-order", action="store_true")
    parser.add_argument("--p1-no-load-env-file", action="store_true")
    parser.add_argument("--p1-no-auto-start-ths-bridge", action="store_true")
    parser.add_argument("--p1-keep-bridge", action="store_true")
    parser.add_argument("--p1-dry-run", action="store_true")

    parser.add_argument("--p2-profile", default="ths_paper_default")
    parser.add_argument("--p2-probe-iterations", type=int, default=80)
    parser.add_argument("--p2-probe-failure-every", type=int, default=9)
    parser.add_argument("--p2-probe-rate-limit-per-minute", type=int, default=90)
    parser.add_argument("--p2-probe-max-wait-ms", type=int, default=0)
    parser.add_argument("--p2-probe-retry-count", type=int, default=2)
    parser.add_argument("--p2-probe-retry-base-ms", type=int, default=30)
    parser.add_argument("--p2-probe-fail-on-quality", choices=["none", "warn", "critical"], default="critical")

    parser.add_argument("--p3-limit", type=int, default=200)
    parser.add_argument("--p3-sample-size", type=int, default=20)
    parser.add_argument("--p3-min-completeness-rate", type=float, default=0.95)
    parser.add_argument("--p3-max-inconsistent-rate", type=float, default=0.02)
    parser.add_argument("--p3-disallow-empty", action="store_true")
    parser.add_argument("--p3-fail-on-warn", action="store_true")
    parser.add_argument("--p3-seed-sample-evidence", action="store_true")
    parser.add_argument("--p3-sample-count", type=int, default=3)

    parser.add_argument("--p4-bars", type=int, default=80)
    parser.add_argument("--p4-data-dir", default="data/p4_smoke")
    parser.add_argument("--p4-run-tag", default="closure")
    parser.add_argument("--p4-sort-by", default="net_pnl")
    parser.add_argument("--p4-top-k", type=int, default=5)
    parser.add_argument("--p4-grid-json", default="")
    parser.add_argument("--p4-max-combinations", type=int, default=128)
    return parser.parse_args()


def _run_command(name: str, cmd: list[str]) -> dict[str, Any]:
    started_at = _iso_now()
    started_perf = time.perf_counter()
    proc = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    duration_ms = round((time.perf_counter() - started_perf) * 1000.0, 3)
    return {
        "name": name,
        "started_at": started_at,
        "finished_at": _iso_now(),
        "duration_ms": duration_ms,
        "returncode": int(proc.returncode),
        "command": cmd,
        "stdout": proc.stdout or "",
        "stderr": proc.stderr or "",
    }


def _build_p1_cmd(args: argparse.Namespace, python_exec: str, paths: dict[str, Path]) -> list[str]:
    cmd = [
        python_exec,
        str(PROJECT_ROOT / "scripts" / "smoke" / "run_sealoff_gate.py"),
        "--profile",
        str(args.p1_profile),
        "--matrix-output",
        str(paths["p1_matrix"]),
        "--oneclick-report-output",
        str(paths["p1_oneclick"]),
        "--sealoff-report-output",
        str(paths["p1_sealoff"]),
    ]
    if args.p1_allow_live_order:
        cmd.append("--allow-live-order")
    if args.p1_no_load_env_file:
        cmd.append("--no-load-env-file")
    if args.p1_no_auto_start_ths_bridge:
        cmd.append("--no-auto-start-ths-bridge")
    if args.p1_keep_bridge:
        cmd.append("--keep-bridge")
    if args.p1_dry_run:
        cmd.append("--dry-run")
    return cmd


def _build_p2_cmd(args: argparse.Namespace, python_exec: str, paths: dict[str, Path]) -> list[str]:
    return [
        python_exec,
        str(PROJECT_ROOT / "scripts" / "dataflow" / "apply_runtime_profile.py"),
        "--profile",
        str(args.p2_profile),
        "--output",
        str(paths["p2_profile"]),
        "--run-stability-probe",
        "--strict-probe",
        "--probe-output",
        str(paths["p2_probe"]),
        "--probe-iterations",
        str(int(args.p2_probe_iterations)),
        "--probe-failure-every",
        str(int(args.p2_probe_failure_every)),
        "--probe-rate-limit-per-minute",
        str(int(args.p2_probe_rate_limit_per_minute)),
        "--probe-max-wait-ms",
        str(int(args.p2_probe_max_wait_ms)),
        "--probe-retry-count",
        str(int(args.p2_probe_retry_count)),
        "--probe-retry-base-ms",
        str(int(args.p2_probe_retry_base_ms)),
        "--probe-fail-on-quality",
        str(args.p2_probe_fail_on_quality),
    ]


def _build_p3_cmd(args: argparse.Namespace, python_exec: str, paths: dict[str, Path]) -> list[str]:
    cmd = [
        python_exec,
        str(PROJECT_ROOT / "scripts" / "evidence" / "validate_evidence_schema.py"),
        "--limit",
        str(int(args.p3_limit)),
        "--sample-size",
        str(int(args.p3_sample_size)),
        "--min-completeness-rate",
        str(float(args.p3_min_completeness_rate)),
        "--max-inconsistent-rate",
        str(float(args.p3_max_inconsistent_rate)),
        "--output",
        str(paths["p3_evidence"]),
    ]
    if args.p3_disallow_empty:
        cmd.append("--disallow-empty")
    if args.p3_fail_on_warn:
        cmd.append("--fail-on-warn")
    if getattr(args, "p3_seed_sample_evidence", False):
        cmd.append("--seed-sample-evidence")
        cmd.extend(["--sample-count", str(max(1, int(getattr(args, "p3_sample_count", 3))))])
    return cmd


def _build_p4_cmd(args: argparse.Namespace, python_exec: str, paths: dict[str, Path]) -> list[str]:
    cmd = [
        python_exec,
        str(PROJECT_ROOT / "scripts" / "strategy" / "p4_lifecycle_smoke.py"),
        "--data-dir",
        str(args.p4_data_dir),
        "--bars",
        str(int(args.p4_bars)),
        "--run-tag",
        str(args.p4_run_tag),
        "--sort-by",
        str(args.p4_sort_by),
        "--top-k",
        str(int(args.p4_top_k)),
        "--max-combinations",
        str(int(args.p4_max_combinations)),
        "--output",
        str(paths["p4_lifecycle"]),
    ]
    if str(args.p4_grid_json or "").strip():
        cmd.extend(["--grid-json", str(args.p4_grid_json)])
    return cmd


def _step_status(step_name: str, returncode: int, report: dict[str, Any]) -> str:
    if returncode != 0:
        return "BLOCK"
    if step_name == "p3_evidence":
        status = str((report.get("gate", {}) or {}).get("status", "PASS")).upper()
        return "PASS" if status == "PASS" else "WARN" if status == "WARN" else "BLOCK"
    if step_name == "p4_lifecycle":
        status = str(report.get("status", "PASS")).upper()
        return "PASS" if status == "PASS" else "BLOCK"
    if step_name == "p1_sealoff":
        summary = report.get("gate_summary", {}) if isinstance(report.get("gate_summary", {}), dict) else {}
        all_passed = bool(summary.get("all_passed", False))
        if all_passed:
            return "PASS"
        return "WARN"
    if step_name == "p2_profile":
        probe = report.get("stability_probe", {}) if isinstance(report.get("stability_probe", {}), dict) else {}
        probe_rc = int(probe.get("returncode", 0) or 0)
        probe_report = probe.get("report", {}) if isinstance(probe.get("report", {}), dict) else {}
        probe_gate = probe_report.get("gate", {}) if isinstance(probe_report.get("gate", {}), dict) else {}
        probe_status = str(probe_gate.get("status", "")).upper()
        if probe_rc != 0:
            return "BLOCK"
        if probe_status == "SKIP":
            return "WARN"
        return "PASS"
    return "PASS"


def _apply_strict_defaults(args: argparse.Namespace) -> None:
    if not args.strict_mode:
        return

    args.fail_fast = True
    args.p1_dry_run = False
    args.p1_allow_live_order = True
    args.p1_no_auto_start_ths_bridge = False
    args.p1_no_load_env_file = False
    args.p1_keep_bridge = False
    args.p2_probe_fail_on_quality = "critical"
    args.p2_probe_failure_every = max(100000, int(args.p2_probe_failure_every))
    args.p3_disallow_empty = True
    args.p3_fail_on_warn = True
    args.p3_seed_sample_evidence = True
    args.p3_sample_count = 5

    if args.strict_level == "ci":
        args.p1_profile = "simulation_strict"
        args.p1_allow_live_order = False
        args.p1_no_load_env_file = True
        args.p1_no_auto_start_ths_bridge = True
    else:
        args.p1_profile = "ths_sim_probe"


def _build_paths(output_dir: Path, stamp: str) -> dict[str, Path]:
    return {
        "p1_matrix": output_dir / f"{stamp}_p1_matrix.json",
        "p1_oneclick": output_dir / f"{stamp}_p1_oneclick.json",
        "p1_sealoff": output_dir / f"{stamp}_p1_sealoff.json",
        "p2_profile": output_dir / f"{stamp}_p2_profile.json",
        "p2_probe": output_dir / f"{stamp}_p2_stability_probe.json",
        "p3_evidence": output_dir / f"{stamp}_p3_evidence.json",
        "p4_lifecycle": output_dir / f"{stamp}_p4_lifecycle.json",
    }


def main() -> int:
    args = _parse_args()
    _apply_strict_defaults(args)
    python_exec = _resolve_python_executable(args.python_executable)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir).expanduser()
    if not output_dir.is_absolute():
        output_dir = PROJECT_ROOT / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    closure_output = Path(args.output).expanduser() if args.output else output_dir / f"{stamp}_p1_p4_closure.json"
    if not closure_output.is_absolute():
        closure_output = PROJECT_ROOT / closure_output
    closure_output.parent.mkdir(parents=True, exist_ok=True)

    paths = _build_paths(output_dir, stamp)
    started_at = _iso_now()
    started_perf = time.perf_counter()

    plan = [
        ("p1_sealoff", _build_p1_cmd(args, python_exec, paths), paths["p1_sealoff"]),
        ("p2_profile", _build_p2_cmd(args, python_exec, paths), paths["p2_profile"]),
        ("p3_evidence", _build_p3_cmd(args, python_exec, paths), paths["p3_evidence"]),
        ("p4_lifecycle", _build_p4_cmd(args, python_exec, paths), paths["p4_lifecycle"]),
    ]

    steps: list[dict[str, Any]] = []
    blocked = False
    for name, cmd, report_path in plan:
        if blocked and args.fail_fast:
            steps.append(
                {
                    "name": name,
                    "status": "SKIP",
                    "reason": "skipped due to fail-fast",
                    "command": cmd,
                    "report_path": str(report_path),
                }
            )
            continue

        run_result = _run_command(name, cmd)
        report = _load_json(report_path)
        status = _step_status(name, run_result["returncode"], report)
        if args.strict_mode and status == "WARN":
            status = "BLOCK"
        step_row = {
            **run_result,
            "status": status,
            "report_path": str(report_path),
            "report_exists": report_path.exists(),
            "report_summary": {
                "keys": list(report.keys())[:15] if isinstance(report, dict) else [],
            },
        }
        steps.append(step_row)
        if status == "BLOCK":
            blocked = True

    counts = {
        "pass": sum(1 for row in steps if row.get("status") == "PASS"),
        "warn": sum(1 for row in steps if row.get("status") == "WARN"),
        "block": sum(1 for row in steps if row.get("status") == "BLOCK"),
        "skip": sum(1 for row in steps if row.get("status") == "SKIP"),
    }
    overall_status = "PASS" if counts["block"] == 0 else "BLOCK"
    duration_ms = round((time.perf_counter() - started_perf) * 1000.0, 3)

    report = {
        "report_version": "1.0",
        "started_at": started_at,
        "finished_at": _iso_now(),
        "duration_ms": duration_ms,
        "overall_status": overall_status,
        "counts": counts,
        "paths": {key: str(value) for key, value in paths.items()},
        "steps": steps,
        "params": {
            "python_executable": python_exec,
            "fail_fast": bool(args.fail_fast),
            "strict_mode": bool(args.strict_mode),
            "strict_level": str(args.strict_level),
            "p1_profile": str(args.p1_profile),
            "p2_profile": str(args.p2_profile),
            "p3_limit": int(args.p3_limit),
            "p3_seed_sample_evidence": bool(getattr(args, "p3_seed_sample_evidence", False)),
            "p3_sample_count": int(getattr(args, "p3_sample_count", 3)),
            "p4_data_dir": str(args.p4_data_dir),
        },
    }
    closure_output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        "[p1-p4-closure] output={output} status={status} pass={p} warn={w} block={b} skip={s}".format(
            output=closure_output,
            status=overall_status,
            p=counts["pass"],
            w=counts["warn"],
            b=counts["block"],
            s=counts["skip"],
        )
    )
    return 0 if overall_status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
