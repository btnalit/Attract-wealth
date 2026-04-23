from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.core.dataflow_profiles import (
    apply_dataflow_env,
    get_dataflow_profile_meta,
    list_dataflow_profiles,
    resolve_dataflow_profile,
)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pick_python_executable() -> str:
    candidates = [
        ROOT_DIR / ".venv" / "Scripts" / "python.exe",
        ROOT_DIR / ".venv" / "Scripts" / "python",
    ]
    for item in candidates:
        if item.exists():
            return str(item)
    return sys.executable


def _default_output_path(profile: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return ROOT_DIR / "data" / "stability" / f"profile_apply_{profile}_{stamp}.json"


def _default_probe_output(profile: str) -> Path:
    return ROOT_DIR / "data" / "stability" / f"profile_probe_{profile}_latest.json"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply a dataflow runtime profile and optionally run stability probe.")
    parser.add_argument("--profile", required=True, choices=sorted(list_dataflow_profiles().keys()))
    parser.add_argument("--output", default="", help="Result report path.")
    parser.add_argument("--run-stability-probe", action="store_true")
    parser.add_argument("--strict-probe", action="store_true", help="Return non-zero when probe gate is blocked.")
    parser.add_argument("--probe-output", default="", help="Probe report path.")
    parser.add_argument("--probe-iterations", type=int, default=80)
    parser.add_argument("--probe-failure-every", type=int, default=9)
    parser.add_argument("--probe-rate-limit-per-minute", type=int, default=90)
    parser.add_argument("--probe-max-wait-ms", type=int, default=0)
    parser.add_argument("--probe-retry-count", type=int, default=2)
    parser.add_argument("--probe-retry-base-ms", type=int, default=30)
    parser.add_argument("--probe-fail-on-quality", choices=["none", "warn", "critical"], default="critical")
    return parser.parse_args()


def _build_probe_cmd(args: argparse.Namespace, output_path: Path) -> list[str]:
    return [
        _pick_python_executable(),
        str(ROOT_DIR / "scripts" / "dataflow" / "stability_probe.py"),
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
        str(output_path),
    ]


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main() -> int:
    args = _parse_args()
    profile_name = str(args.profile or "").strip().lower()
    profile_env = resolve_dataflow_profile(profile_name)
    if not profile_env:
        print(f"[profile-apply] unknown profile: {profile_name}")
        return 2
    profile_meta = get_dataflow_profile_meta(profile_name)

    started_at = _iso_now()
    output_path = Path(args.output).expanduser() if args.output else _default_output_path(profile_name)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    applied_env = apply_dataflow_env(profile_env)
    runtime_config: dict[str, Any] = {}
    summary: dict[str, Any] = {}
    quality: dict[str, Any] = {}
    tuning: dict[str, Any] = {}
    degraded_error = ""

    try:
        from src.dataflows.source_manager import data_manager

        runtime_config = data_manager.reload_runtime_config_from_env()
        metrics = data_manager.get_metrics()
        runtime_config = metrics.get("runtime_config", runtime_config)
        summary = metrics.get("summary", {})
        quality = metrics.get("quality", {})
        tuning = metrics.get("tuning", {})
    except Exception as exc:  # noqa: BLE001
        degraded_error = str(exc)

    probe_info: dict[str, Any] = {"enabled": bool(args.run_stability_probe), "returncode": None}
    if args.run_stability_probe:
        probe_output = Path(args.probe_output).expanduser() if args.probe_output else _default_probe_output(profile_name)
        probe_output.parent.mkdir(parents=True, exist_ok=True)
        cmd = _build_probe_cmd(args, probe_output)
        proc = subprocess.run(cmd, cwd=str(ROOT_DIR), check=False)
        probe_info = {
            "enabled": True,
            "command": cmd,
            "returncode": proc.returncode,
            "output": str(probe_output),
            "report": _load_json(probe_output),
        }

    report = {
        "report_version": "1.0",
        "started_at": started_at,
        "finished_at": _iso_now(),
        "profile": profile_name,
        "profile_version": str(profile_meta.get("version", "")),
        "profile_description": str(profile_meta.get("description", "")),
        "applied_env": applied_env,
        "runtime_config": runtime_config,
        "summary": summary,
        "quality": quality,
        "tuning": tuning,
        "degraded_error": degraded_error,
        "stability_probe": probe_info,
    }
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[profile-apply] profile={profile_name}")
    if profile_meta:
        print(
            "[profile-apply] profile_meta version={version} description={desc}".format(
                version=profile_meta.get("version", ""),
                desc=profile_meta.get("description", ""),
            )
        )
    print(f"[profile-apply] output={output_path}")
    if degraded_error:
        print(f"[profile-apply] runtime degraded: {degraded_error}")

    if args.strict_probe and args.run_stability_probe and int(probe_info.get("returncode") or 0) != 0:
        return int(probe_info.get("returncode") or 1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
