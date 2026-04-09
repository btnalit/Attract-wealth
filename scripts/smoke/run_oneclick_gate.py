from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_THS_BRIDGE_SCRIPT = Path(r"D:\同花顺软件\同花顺\script\laicai_bridge.py")
DEFAULT_SMOKE_CHANNELS = "ths_ipc,simulation"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _split_channels(raw: str) -> list[str]:
    return [item.strip().lower() for item in str(raw).split(",") if item.strip()]


def _resolve_path(path_like: str) -> Path:
    path = Path(path_like)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _wait_port(host: str, port: int, timeout_s: float) -> tuple[bool, str]:
    deadline = time.time() + max(0.2, float(timeout_s))
    last_error = ""
    while time.time() < deadline:
        sock = socket.socket()
        sock.settimeout(1.0)
        try:
            sock.connect((host, port))
            return True, ""
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            time.sleep(0.25)
        finally:
            try:
                sock.close()
            except Exception:  # noqa: BLE001
                pass
    return False, last_error or "timeout"


def _default_matrix_report_path() -> str:
    return "data/smoke/reports/matrix_strict_latest.json"


def _default_orchestrator_report_path() -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"data/smoke/reports/oneclick_gate_{stamp}.json"


def _default_bridge_stdout_path() -> str:
    return "data/smoke/reports/ths_bridge_stdout.log"


def _default_bridge_stderr_path() -> str:
    return "data/smoke/reports/ths_bridge_stderr.log"


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_env_file(path: Path) -> tuple[bool, list[str]]:
    if not path.exists():
        return False, []

    loaded_keys: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue

        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]

        if key not in os.environ:
            os.environ[key] = value
            loaded_keys.append(key)

    return True, loaded_keys


def _extract_hints_from_matrix(matrix: dict[str, Any]) -> list[str]:
    hints: list[str] = []
    for row in matrix.get("results", []):
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
            hints.append("THS IPC bridge 未就绪：请确认同花顺已运行 bridge 脚本。")
        if "ths_exe_path not found" in reason:
            hints.append("THS_AUTO 客户端路径无效：请设置正确 THS_EXE_PATH。")
        if "stub-only" in reason:
            hints.append("THS_AUTO 仍是骨架实现：建议改用 ths_ipc/qmt，或仅测试时启用 THS_AUTO_ALLOW_STUB=true。")
        if not reason:
            hints.append(f"{channel} 联调失败：请查看单通道报告 checks/stderr。")

    stability = matrix.get("stability_probe", {}) if isinstance(matrix.get("stability_probe", {}), dict) else {}
    if not stability.get("gate_ok", True):
        status = str(stability.get("status", "")).upper()
        if status == "BLOCK":
            hints.append("稳定性压测触发 BLOCK：请按 tuning.suggested_env 调参后重试。")

        suggested_env = (stability.get("tuning", {}) or {}).get("suggested_env", {}) or {}
        for key, value in suggested_env.items():
            hints.append(f"建议调参：{key}={value}")

        gate = stability.get("gate", {}) if isinstance(stability.get("gate", {}), dict) else {}
        for row in gate.get("failed_rules", []) or []:
            hints.append(f"稳定性门禁失败：{row.get('rule')} -> {row.get('detail')}")

    budget_probe = (
        matrix.get("budget_recovery_probe", {})
        if isinstance(matrix.get("budget_recovery_probe", {}), dict)
        else {}
    )
    if not budget_probe.get("gate_ok", True):
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
        gate = budget_probe.get("gate", {}) if isinstance(budget_probe.get("gate", {}), dict) else {}
        for row in gate.get("failed_rules", []) or []:
            hints.append(f"预算恢复门禁失败：{row.get('rule')} -> {row.get('detail')}")

    deduped: list[str] = []
    for item in hints:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _build_strict_gate_cmd(args: argparse.Namespace, matrix_output: Path) -> list[str]:
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "smoke" / "run_strict_gate.py"),
        "--channels",
        args.channels,
        "--output",
        str(matrix_output),
    ]
    if args.include_order_probe:
        cmd.append("--include-order-probe")
    if args.force_live_order:
        cmd.append("--force-live-order")
    if args.no_reconcile:
        cmd.append("--no-reconcile")
    if args.no_stability_probe:
        cmd.append("--no-stability-probe")
    else:
        cmd.extend(
            [
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
    if args.no_budget_recovery_probe:
        cmd.append("--no-budget-recovery-probe")
    else:
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


def _build_check_only_cmd(args: argparse.Namespace, matrix_output: Path) -> list[str]:
    cmd = _build_strict_gate_cmd(args, matrix_output)
    cmd.append("--check-only")
    return cmd


def _open_log(path: Path) -> TextIO:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.open("a", encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="One-click gate runner: start THS bridge then run strict smoke gate.")
    parser.add_argument("--channels", default=os.getenv("SMOKE_DEFAULT_CHANNELS", DEFAULT_SMOKE_CHANNELS))
    parser.add_argument("--include-order-probe", action="store_true")
    parser.add_argument("--force-live-order", action="store_true")
    parser.add_argument("--no-reconcile", action="store_true")
    parser.add_argument("--no-stability-probe", action="store_true")
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

    parser.add_argument("--auto-start-ths-bridge", action="store_true", default=True)
    parser.add_argument("--no-auto-start-ths-bridge", action="store_true")
    parser.add_argument("--ths-bridge-script", default=os.getenv("THS_BRIDGE_SCRIPT", str(DEFAULT_THS_BRIDGE_SCRIPT)))
    parser.add_argument("--ths-bridge-python", default=os.getenv("THS_BRIDGE_PYTHON", sys.executable))
    parser.add_argument(
        "--ths-bridge-command",
        default=os.getenv("THS_BRIDGE_START_COMMAND", ""),
        help="Optional shell command to start bridge (takes precedence over python+script).",
    )
    parser.add_argument("--ths-bridge-host", default=os.getenv("THS_IPC_HOST", "127.0.0.1"))
    parser.add_argument("--ths-bridge-port", type=int, default=int(os.getenv("THS_IPC_PORT", "8089")))
    parser.add_argument("--ths-bridge-timeout", type=float, default=12.0)
    parser.add_argument("--bridge-stdout", default=_default_bridge_stdout_path())
    parser.add_argument("--bridge-stderr", default=_default_bridge_stderr_path())
    parser.add_argument("--keep-bridge", action="store_true", help="Keep bridge process alive after run.")

    parser.add_argument("--precheck-first", action="store_true", default=True, help="Run strict precheck first.")
    parser.add_argument("--no-precheck-first", action="store_true", help="Skip check-only precheck phase.")
    parser.add_argument("--fail-fast-precheck", action="store_true", default=True, help="Fail fast on precheck errors.")
    parser.add_argument("--no-fail-fast-precheck", action="store_true", help="Ignore precheck failure and continue.")

    parser.add_argument("--env-file", default=".env", help="Optional env file loaded before running gate.")
    parser.add_argument("--no-load-env-file", action="store_true", help="Disable loading env file.")

    parser.add_argument("--matrix-output", default=_default_matrix_report_path())
    parser.add_argument("--report-output", default=_default_orchestrator_report_path())
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.no_auto_start_ths_bridge:
        args.auto_start_ths_bridge = False
    if args.no_precheck_first:
        args.precheck_first = False
    if args.no_fail_fast_precheck:
        args.fail_fast_precheck = False

    env_status: dict[str, Any] = {
        "enabled": not args.no_load_env_file,
        "path": str(_resolve_path(args.env_file)),
        "exists": False,
        "loaded_keys": [],
    }
    if not args.no_load_env_file:
        exists, loaded_keys = _load_env_file(_resolve_path(args.env_file))
        env_status["exists"] = exists
        env_status["loaded_keys"] = loaded_keys

    channels = _split_channels(args.channels)
    started_at = _iso_now()
    matrix_path = _resolve_path(args.matrix_output)
    report_path = _resolve_path(args.report_output)

    bridge_stdout_path = _resolve_path(args.bridge_stdout)
    bridge_stderr_path = _resolve_path(args.bridge_stderr)
    bridge_stdout_log: TextIO | None = None
    bridge_stderr_log: TextIO | None = None

    bridge: dict[str, Any] = {
        "requested": bool(args.auto_start_ths_bridge and "ths_ipc" in channels),
        "started": False,
        "existing": False,
        "pid": None,
        "ready": False,
        "message": "",
        "host": args.ths_bridge_host,
        "port": args.ths_bridge_port,
        "script": str(_resolve_path(args.ths_bridge_script)),
        "python": args.ths_bridge_python,
        "start_command": str(args.ths_bridge_command or ""),
        "stdout_log": str(bridge_stdout_path),
        "stderr_log": str(bridge_stderr_path),
    }
    bridge_proc: subprocess.Popen[Any] | None = None
    precheck_proc: subprocess.CompletedProcess[Any] | None = None

    if bridge["requested"]:
        already_ready, _ = _wait_port(args.ths_bridge_host, args.ths_bridge_port, 0.25)
        if already_ready:
            bridge["existing"] = True
            bridge["ready"] = True
            bridge["message"] = "already listening"
        else:
            script_path = _resolve_path(args.ths_bridge_script)
            if not args.ths_bridge_command and not script_path.exists():
                bridge["message"] = f"bridge script not found: {script_path}"
            else:
                try:
                    bridge_stdout_log = _open_log(bridge_stdout_path)
                    bridge_stderr_log = _open_log(bridge_stderr_path)
                    if args.ths_bridge_command:
                        bridge_proc = subprocess.Popen(
                            args.ths_bridge_command,
                            stdout=bridge_stdout_log,
                            stderr=bridge_stderr_log,
                            cwd=str(PROJECT_ROOT),
                            shell=True,
                        )
                    else:
                        bridge_proc = subprocess.Popen(
                            [args.ths_bridge_python, str(script_path)],
                            stdout=bridge_stdout_log,
                            stderr=bridge_stderr_log,
                            cwd=str(script_path.parent),
                        )
                    bridge["started"] = True
                    bridge["pid"] = bridge_proc.pid
                    ready, reason = _wait_port(args.ths_bridge_host, args.ths_bridge_port, args.ths_bridge_timeout)
                    bridge["ready"] = ready
                    bridge["message"] = "ready" if ready else f"port not ready: {reason}"
                except Exception as exc:  # noqa: BLE001
                    bridge["message"] = f"start failed: {exc}"

    if args.precheck_first:
        precheck_cmd = _build_check_only_cmd(args, matrix_path)
        precheck_proc = subprocess.run(precheck_cmd, check=False, cwd=str(PROJECT_ROOT))
        if precheck_proc.returncode != 0 and args.fail_fast_precheck:
            report = {
                "report_version": "1.2",
                "started_at": started_at,
                "finished_at": _iso_now(),
                "inputs": {
                    "channels": channels,
                    "include_order_probe": bool(args.include_order_probe),
                    "force_live_order": bool(args.force_live_order),
                    "no_reconcile": bool(args.no_reconcile),
                    "no_stability_probe": bool(args.no_stability_probe),
                    "no_budget_recovery_probe": bool(args.no_budget_recovery_probe),
                    "auto_start_ths_bridge": bool(args.auto_start_ths_bridge),
                    "keep_bridge": bool(args.keep_bridge),
                    "env_file": env_status,
                    "precheck_first": True,
                    "fail_fast_precheck": True,
                },
                "bridge": bridge,
                "gate": {
                    "returncode": precheck_proc.returncode,
                    "all_passed": False,
                    "counts": {},
                    "hints": ["前置校验失败，已 fail-fast；请先修复 precheck 提示后重试。"],
                    "command": precheck_cmd,
                    "precheck_returncode": precheck_proc.returncode,
                    "matrix_returncode": None,
                    "matrix_report": str(matrix_path),
                },
            }
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

            if bridge_stdout_log:
                bridge_stdout_log.close()
            if bridge_stderr_log:
                bridge_stderr_log.close()
            if bridge_proc is not None and not args.keep_bridge:
                if bridge_proc.poll() is None:
                    bridge_proc.terminate()
            print(f"[oneclick-gate] report={report_path}")
            print(f"[oneclick-gate] fail-fast precheck failed, returncode={precheck_proc.returncode}")
            return precheck_proc.returncode

    cmd = _build_strict_gate_cmd(args, matrix_path)
    proc = subprocess.run(cmd, check=False, cwd=str(PROJECT_ROOT))

    matrix = _load_json(matrix_path)
    hints = _extract_hints_from_matrix(matrix) if matrix else []

    gate_summary = {
        "returncode": proc.returncode,
        "matrix_report": str(matrix_path),
        "all_passed": bool(matrix.get("all_passed", False)) if matrix else False,
        "counts": matrix.get("counts", {}) if matrix else {},
        "hints": hints,
        "command": cmd,
        "precheck_returncode": precheck_proc.returncode if precheck_proc is not None else None,
        "matrix_returncode": proc.returncode,
    }

    if bridge_proc is not None and not args.keep_bridge:
        if bridge_proc.poll() is None:
            bridge_proc.terminate()
            try:
                bridge_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                bridge_proc.kill()
        bridge["stopped"] = True
    else:
        bridge["stopped"] = False

    if bridge_stdout_log:
        bridge_stdout_log.close()
    if bridge_stderr_log:
        bridge_stderr_log.close()

    report = {
        "report_version": "1.2",
        "started_at": started_at,
        "finished_at": _iso_now(),
        "inputs": {
            "channels": channels,
            "include_order_probe": bool(args.include_order_probe),
            "force_live_order": bool(args.force_live_order),
            "no_reconcile": bool(args.no_reconcile),
            "no_stability_probe": bool(args.no_stability_probe),
            "no_budget_recovery_probe": bool(args.no_budget_recovery_probe),
            "auto_start_ths_bridge": bool(args.auto_start_ths_bridge),
            "keep_bridge": bool(args.keep_bridge),
            "env_file": env_status,
            "precheck_first": bool(args.precheck_first),
            "fail_fast_precheck": bool(args.fail_fast_precheck),
        },
        "bridge": bridge,
        "gate": gate_summary,
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[oneclick-gate] report={report_path}")
    print(
        "[oneclick-gate] bridge_ready={bridge_ready} all_passed={all_passed} returncode={code}".format(
            bridge_ready=bridge.get("ready", False),
            all_passed=gate_summary["all_passed"],
            code=proc.returncode,
        )
    )
    if hints:
        print("[oneclick-gate] hints:")
        for idx, hint in enumerate(hints, start=1):
            print(f"  {idx}. {hint}")

    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
