from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.startup_preflight import run_startup_preflight

DEFAULT_SMOKE_CHANNELS = "ths_ipc,simulation"


@dataclass
class PrecheckResult:
    name: str
    ok: bool
    severity: str
    message: str
    hint: str = ""


def _resolve_path(path_like: str) -> Path:
    path = Path(path_like)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def resolve_python_executable() -> str:
    candidates = [
        PROJECT_ROOT / ".venv" / "Scripts" / "python.exe",
        PROJECT_ROOT / ".venv" / "Scripts" / "python",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return sys.executable


def run_prechecks(channels: list[str], *, with_stability_probe: bool) -> list[PrecheckResult]:
    rows: list[PrecheckResult] = []
    seen_names: set[str] = set()
    for index, channel in enumerate(channels):
        report = run_startup_preflight(
            channel=channel,
            include_stability_probe=with_stability_probe and index == 0,
        )
        for item in report.get("checks", []):
            name = str(item.get("name", "unknown"))
            if name == "pandas_module" and name in seen_names:
                continue
            seen_names.add(name)
            rows.append(
                PrecheckResult(
                    name=f"{channel}:{name}",
                    ok=bool(item.get("ok", False)),
                    severity=str(item.get("severity", "critical")),
                    message=str(item.get("message", "")),
                    hint=str(item.get("hint", "")),
                )
            )
    return rows


def print_prechecks(results: list[PrecheckResult]) -> None:
    print("[strict-gate] Prechecks:")
    for item in results:
        status = "OK" if item.ok else ("WARN" if item.severity != "critical" else "FAIL")
        print(f"  - [{status}] {item.name}: {item.message}")
        if not item.ok and item.hint:
            print(f"      hint: {item.hint}")


def build_matrix_command(args: argparse.Namespace) -> list[str]:
    output_path = _resolve_path(args.output)
    cmd = [
        resolve_python_executable(),
        str(PROJECT_ROOT / "scripts" / "smoke" / "run_channel_matrix.py"),
        "--channels",
        args.channels,
        "--disallow-skip",
        "--strict-preflight",
        "--output",
        str(output_path),
    ]
    if not args.no_reconcile:
        cmd.append("--include-reconcile")
    if args.include_order_probe:
        cmd.append("--include-order-probe")
    if args.force_live_order:
        cmd.append("--force-live-order")
    if args.with_stability_probe:
        cmd.extend(
            [
                "--with-stability-probe",
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
            ]
        )
    if args.with_budget_recovery_probe:
        cmd.extend(
            [
                "--with-budget-recovery-probe",
                "--budget-probe-cycles",
                str(args.budget_probe_cycles),
                "--budget-probe-active-steps",
                str(args.budget_probe_active_steps),
                "--budget-probe-recovery-steps",
                str(args.budget_probe_recovery_steps),
                "--budget-probe-interval-ms",
                str(args.budget_probe_interval_ms),
                "--budget-probe-budget-usd",
                str(args.budget_probe_budget_usd),
                "--budget-probe-exceed-cost",
                str(args.budget_probe_exceed_cost),
                "--budget-probe-recover-cost",
                str(args.budget_probe_recover_cost),
                "--budget-probe-recovery-ratio",
                str(args.budget_probe_recovery_ratio),
                "--budget-probe-cooldown-s",
                str(args.budget_probe_cooldown_s),
                "--budget-probe-action",
                str(args.budget_probe_action),
                "--budget-probe-min-success-rate",
                str(args.budget_probe_min_success_rate),
                "--budget-probe-max-avg-recovery-s",
                str(args.budget_probe_max_avg_recovery_s),
            ]
        )
    return cmd


def extract_failure_hints(report: dict[str, Any]) -> list[str]:
    hints: list[str] = []

    for row in report.get("results", []):
        if row.get("gate_ok", False):
            continue
        channel = str(row.get("channel", "unknown"))
        preflight = row.get("preflight", {}) if isinstance(row.get("preflight", {}), dict) else {}
        reason = str(preflight.get("reason", "")).lower()

        if "missing qmt_account_id" in reason or "missing qmt_account" in reason:
            hints.append("QMT 账户未配置：请设置 QMT_ACCOUNT_ID（或 QMT_ACCOUNT）。")
        if "qmt_path not found" in reason or "missing qmt_path" in reason:
            hints.append("QMT 路径不可用：请确认 QMT_PATH 指向有效客户端目录。")
        if "xtquant" in reason:
            hints.append("xtquant 不可用：请在当前解释器安装券商 xtquant 包。")
        if "ths_ipc bridge unavailable" in reason or "unreachable" in reason:
            hints.append("THS IPC bridge 未就绪：请启动 laicai_bridge 并确认端口连通。")
        if "ths_exe_path not found" in reason:
            hints.append("THS_AUTO 客户端路径无效：请设置正确 THS_EXE_PATH。")
        if "stub-only" in reason:
            hints.append("THS_AUTO 仍为骨架实现：建议改用 ths_ipc/qmt，或仅测试时启用 THS_AUTO_ALLOW_STUB=true。")
        if not reason:
            hints.append(f"{channel} 联调失败：请查看对应 report 的 checks/stderr。")

    stability = report.get("stability_probe", {}) if isinstance(report.get("stability_probe", {}), dict) else {}
    if not stability.get("gate_ok", True):
        gate = stability.get("gate", {}) if isinstance(stability.get("gate", {}), dict) else {}
        status = str(stability.get("status", "")).upper()
        if status == "BLOCK":
            hints.append("稳定性压测触发 BLOCK：请根据 tuning.suggested_env 调整限流/重试参数。")
        for key, value in (stability.get("tuning", {}) or {}).get("suggested_env", {}).items():
            hints.append(f"建议调参：{key}={value}")
        for row in gate.get("failed_rules", []) or []:
            hints.append(f"稳定性门禁失败：{row.get('rule')} -> {row.get('detail')}")

    budget_probe = (
        report.get("budget_recovery_probe", {})
        if isinstance(report.get("budget_recovery_probe", {}), dict)
        else {}
    )
    if not budget_probe.get("gate_ok", True):
        gate = budget_probe.get("gate", {}) if isinstance(budget_probe.get("gate", {}), dict) else {}
        status = str(budget_probe.get("status", "")).upper()
        if status == "BLOCK":
            hints.append("预算恢复压测触发 BLOCK：请检查恢复成功率与平均恢复时长阈值。")
        summary = budget_probe.get("summary", {}) if isinstance(budget_probe.get("summary", {}), dict) else {}
        if summary:
            hints.append(
                "预算恢复观测：success_rate={rate:.4f}, avg_recovery_s={avg:.4f}".format(
                    rate=float(summary.get("recovery_success_rate", 0.0)),
                    avg=float(summary.get("avg_recovery_duration_s", 0.0)),
                )
            )
        for row in gate.get("failed_rules", []) or []:
            hints.append(f"预算恢复门禁失败：{row.get('rule')} -> {row.get('detail')}")

    deduped: list[str] = []
    for item in hints:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Strict gate runner for THS/QMT/Simulation smoke regression.")
    parser.add_argument("--channels", default=os.getenv("SMOKE_DEFAULT_CHANNELS", DEFAULT_SMOKE_CHANNELS))
    parser.add_argument("--include-order-probe", action="store_true")
    parser.add_argument("--force-live-order", action="store_true")
    parser.add_argument("--no-reconcile", action="store_true", help="Skip reconciliation probe in matrix smoke.")
    parser.add_argument("--with-stability-probe", action="store_true", default=True)
    parser.add_argument("--no-stability-probe", action="store_true")
    parser.add_argument("--with-budget-recovery-probe", action="store_true", default=True)
    parser.add_argument("--no-budget-recovery-probe", action="store_true")
    parser.add_argument("--probe-iterations", type=int, default=80)
    parser.add_argument("--probe-failure-every", type=int, default=4)
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
    parser.add_argument("--check-only", action="store_true", help="Only run prechecks, do not execute matrix.")
    parser.add_argument(
        "--output",
        default="data/smoke/reports/matrix_strict_latest.json",
        help="Matrix report path.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.no_stability_probe:
        args.with_stability_probe = False
    if args.no_budget_recovery_probe:
        args.with_budget_recovery_probe = False

    channels = [item.strip() for item in str(args.channels).split(",") if item.strip()]
    prechecks = run_prechecks(channels, with_stability_probe=bool(args.with_stability_probe))
    print_prechecks(prechecks)

    hard_failures = [item for item in prechecks if not item.ok and item.severity == "critical"]
    warning_failures = [item for item in prechecks if not item.ok and item.severity != "critical"]
    if hard_failures:
        print(f"[strict-gate] precheck failed: {len(hard_failures)} item(s).")
        if args.check_only:
            return 2
    if warning_failures:
        print(f"[strict-gate] precheck warnings: {len(warning_failures)} item(s).")

    if args.check_only:
        print("[strict-gate] check-only done.")
        return 0 if not hard_failures else 2

    cmd = build_matrix_command(args)
    print("[strict-gate] running matrix command:")
    print("  " + " ".join(cmd))
    proc = subprocess.run(cmd, check=False, cwd=str(PROJECT_ROOT))

    report_path = _resolve_path(args.output)
    report = _load_json(report_path)
    if report:
        print(f"[strict-gate] report={report_path}")
        print(
            "[strict-gate] all_passed={all_passed} pass={p} skip={s} fail={f}".format(
                all_passed=report.get("all_passed", False),
                p=report.get("counts", {}).get("pass", 0),
                s=report.get("counts", {}).get("skip", 0),
                f=report.get("counts", {}).get("fail", 0),
            )
        )
        hints = extract_failure_hints(report)
        if hints:
            print("[strict-gate] failure hints:")
            for idx, hint in enumerate(hints, start=1):
                print(f"  {idx}. {hint}")

    if proc.returncode != 0:
        return proc.returncode
    if hard_failures:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
