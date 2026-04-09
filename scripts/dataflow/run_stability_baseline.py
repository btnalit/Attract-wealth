from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]


def _default_output_path() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return ROOT_DIR / "data" / "stability" / f"stability_baseline_{stamp}.json"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run dataflow stability baseline across runtime profiles.")
    parser.add_argument(
        "--profiles",
        default="dev_default,sim_default,prod_live",
        help="Comma separated profile names.",
    )
    parser.add_argument("--probe-iterations", type=int, default=80)
    parser.add_argument("--probe-failure-every", type=int, default=4)
    parser.add_argument("--probe-rate-limit-per-minute", type=int, default=90)
    parser.add_argument("--probe-max-wait-ms", type=int, default=0)
    parser.add_argument("--probe-retry-count", type=int, default=2)
    parser.add_argument("--probe-retry-base-ms", type=int, default=30)
    parser.add_argument("--probe-fail-on-quality", choices=["none", "warn", "critical"], default="critical")
    parser.add_argument("--output", default="", help="Output report path.")
    return parser.parse_args()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _run_profile(args: argparse.Namespace, profile: str, report_dir: Path) -> dict[str, Any]:
    profile_name = str(profile or "").strip().lower()
    apply_output = report_dir / f"profile_apply_{profile_name}_baseline.json"
    probe_output = report_dir / f"profile_probe_{profile_name}_baseline.json"
    cmd = [
        sys.executable,
        str(ROOT_DIR / "scripts" / "dataflow" / "apply_runtime_profile.py"),
        "--profile",
        profile_name,
        "--run-stability-probe",
        "--strict-probe",
        "--probe-iterations",
        str(args.probe_iterations),
        "--probe-failure-every",
        str(args.probe_failure_every),
        "--probe-rate-limit-per-minute",
        str(args.probe_rate_limit_per_minute),
        "--probe-max-wait-ms",
        str(args.probe_max_wait_ms),
        "--probe-retry-count",
        str(args.probe_retry_count),
        "--probe-retry-base-ms",
        str(args.probe_retry_base_ms),
        "--probe-fail-on-quality",
        str(args.probe_fail_on_quality),
        "--probe-output",
        str(probe_output),
        "--output",
        str(apply_output),
    ]
    proc = subprocess.run(cmd, cwd=str(ROOT_DIR), capture_output=True, text=True, check=False)
    apply_report = _load_json(apply_output)
    probe_report = _load_json(probe_output)
    probe_gate = probe_report.get("gate", {}) if isinstance(probe_report.get("gate", {}), dict) else {}
    summary = probe_report.get("summary", {}) if isinstance(probe_report.get("summary", {}), dict) else {}
    status = "PASS"
    if proc.returncode != 0:
        status = "FAIL"
    elif str(probe_gate.get("status", "")).upper() == "BLOCK":
        status = "FAIL"

    return {
        "profile": profile_name,
        "status": status,
        "returncode": int(proc.returncode),
        "apply_report": str(apply_output),
        "probe_report": str(probe_output),
        "probe_gate": probe_gate,
        "probe_summary": summary,
        "apply_summary": apply_report.get("summary", {}) if isinstance(apply_report, dict) else {},
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def main() -> int:
    args = _parse_args()
    profiles = [item.strip() for item in str(args.profiles).split(",") if item.strip()]
    if not profiles:
        print("[stability-baseline] no profiles specified")
        return 2

    report_dir = ROOT_DIR / "data" / "stability"
    report_dir.mkdir(parents=True, exist_ok=True)
    rows = [_run_profile(args, profile, report_dir) for profile in profiles]

    pass_count = sum(1 for row in rows if row["status"] == "PASS")
    fail_count = sum(1 for row in rows if row["status"] != "PASS")
    worst_retry_rate = max(float((row.get("probe_summary", {}) or {}).get("retry_rate", 0.0)) for row in rows)
    worst_rate_limited_rate = max(
        float((row.get("probe_summary", {}) or {}).get("rate_limited_rate", 0.0)) for row in rows
    )
    all_passed = fail_count == 0

    report = {
        "report_version": "1.0",
        "generated_at": datetime.now().isoformat(),
        "profiles": profiles,
        "counts": {"pass": pass_count, "fail": fail_count},
        "all_passed": all_passed,
        "baseline": {
            "worst_retry_rate": round(worst_retry_rate, 6),
            "worst_rate_limited_rate": round(worst_rate_limited_rate, 6),
        },
        "results": rows,
    }

    output_path = Path(args.output).expanduser() if args.output else _default_output_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    latest_path = ROOT_DIR / "data" / "stability" / "stability_baseline_latest.json"
    latest_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        "[stability-baseline] output={output} all_passed={passed} pass={p} fail={f}".format(
            output=output_path,
            passed=all_passed,
            p=pass_count,
            f=fail_count,
        )
    )
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
