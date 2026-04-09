from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.execution.ths_auto.easytrader_adapter import inspect_easytrader_runtime, resolve_ths_exe_path  # noqa: E402

DEFAULT_EXE_PATH = r"D:\同花顺软件\同花顺\xiadan.exe"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve(path_like: str) -> Path:
    path = Path(path_like).expanduser()
    if path.is_absolute():
        return path
    return (PROJECT_ROOT / path).resolve()


def _default_probe_output() -> Path:
    return PROJECT_ROOT / "data" / "smoke" / "reports" / "ths_easytrader_probe_latest.json"


def _default_output() -> Path:
    return PROJECT_ROOT / "data" / "smoke" / "reports" / "ths_easytrader_setup_and_probe_latest.json"


def _common_python32_candidates() -> list[Path]:
    return [
        Path(r"C:\Python313-32\python.exe"),
        Path(r"C:\Python312-32\python.exe"),
        Path(r"C:\Python311-32\python.exe"),
        Path(r"C:\Python310-32\python.exe"),
        Path(r"C:\Python39-32\python.exe"),
        Path(r"C:\Program Files (x86)\Python313-32\python.exe"),
        Path(r"C:\Program Files (x86)\Python312-32\python.exe"),
        Path(r"C:\Program Files (x86)\Python311-32\python.exe"),
        Path(r"C:\Program Files (x86)\Python310-32\python.exe"),
        Path(r"C:\Program Files (x86)\Python39-32\python.exe"),
    ]


def _resolve_python32(explicit: str = "") -> str:
    ordered: list[Path] = []
    if explicit:
        ordered.append(Path(explicit).expanduser())
    env_path = os.getenv("THS_EASYTRADER_PYTHON32", "").strip()
    if env_path:
        ordered.append(Path(env_path).expanduser())
    ordered.extend(_common_python32_candidates())

    seen: set[str] = set()
    for path in ordered:
        text = str(path)
        if not text or text in seen:
            continue
        seen.add(text)
        if path.exists():
            return str(path)
    return ""


def _merge_pythonpath(extra_paths: list[str]) -> dict[str, str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "").strip()
    paths = [str(PROJECT_ROOT)]
    for item in extra_paths:
        text = str(item or "").strip()
        if text:
            paths.append(text)
    if existing:
        paths.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    return env


def _run_cmd(cmd: list[str], *, env: dict[str, str] | None = None, timeout_s: int = 300) -> dict[str, Any]:
    started = time.time()
    proc = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=timeout_s,
    )
    return {
        "command": cmd,
        "returncode": int(proc.returncode),
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "elapsed_ms": round((time.time() - started) * 1000, 3),
    }


def _extract_json_from_text(text: str) -> dict[str, Any]:
    if not text:
        return {}
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in reversed(lines):
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def _python_bits(python_exec: str) -> int:
    result = _run_cmd([python_exec, "-c", "import sys;print(64 if sys.maxsize > 2**32 else 32)"], timeout_s=20)
    if result["returncode"] != 0:
        return 0
    try:
        return int((result["stdout"] or "").strip().splitlines()[-1].strip())
    except Exception:
        return 0


def _check_dependencies(python_exec: str, repo_path: str) -> dict[str, Any]:
    code = (
        "import importlib.util, json; "
        "mods={'easyutils':'easyutils','pywinauto':'pywinauto','pandas':'pandas','PIL':'Pillow','requests':'requests','urllib3':'urllib3','ddddocr':'ddddocr'}; "
        "missing=[pkg for mod,pkg in mods.items() if importlib.util.find_spec(mod) is None]; "
        "easytrader_ok=importlib.util.find_spec('easytrader') is not None; "
        "print(json.dumps({'missing':missing,'easytrader_ok':easytrader_ok},ensure_ascii=False))"
    )
    env = _merge_pythonpath([repo_path] if repo_path else [])
    result = _run_cmd([python_exec, "-c", code], env=env, timeout_s=40)
    payload = _extract_json_from_text(result.get("stdout", ""))
    missing = payload.get("missing", []) if isinstance(payload.get("missing", []), list) else []
    return {
        "ok": result["returncode"] == 0,
        "returncode": result["returncode"],
        "missing": [str(item) for item in missing if str(item).strip()],
        "easytrader_ok": bool(payload.get("easytrader_ok", False)),
        "stdout": result["stdout"],
        "stderr": result["stderr"],
    }


def _install_dependencies(python_exec: str, packages: list[str], *, use_user: bool) -> dict[str, Any]:
    if not packages:
        return {"ok": True, "skipped": True, "packages": [], "returncode": 0, "stdout": "", "stderr": ""}
    cmd = [python_exec, "-m", "pip", "install"]
    if use_user:
        cmd.append("--user")
    cmd.extend(packages)
    result = _run_cmd(cmd, timeout_s=600)
    return {
        "ok": result["returncode"] == 0,
        "skipped": False,
        "packages": packages,
        "returncode": result["returncode"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
    }


def _runtime_check_with_python(python_exec: str, exe_path: str) -> dict[str, Any]:
    code = (
        "import json; "
        "from src.execution.ths_auto.easytrader_adapter import inspect_easytrader_runtime; "
        f"print(json.dumps(inspect_easytrader_runtime(exe_path=r'{exe_path}'), ensure_ascii=False))"
    )
    result = _run_cmd([python_exec, "-c", code], env=_merge_pythonpath([]), timeout_s=40)
    payload = _extract_json_from_text(result.get("stdout", ""))
    return {
        "ok": result["returncode"] == 0 and bool(payload),
        "returncode": result["returncode"],
        "runtime": payload,
        "stdout": result["stdout"],
        "stderr": result["stderr"],
    }


def _extract_key_info(probe_report: dict[str, Any]) -> dict[str, Any]:
    probe = probe_report.get("probe", {}) if isinstance(probe_report.get("probe", {}), dict) else {}
    summary = probe.get("summary", {}) if isinstance(probe.get("summary", {}), dict) else {}
    account = probe.get("account", {}) if isinstance(probe.get("account", {}), dict) else {}
    positions = probe.get("positions", []) if isinstance(probe.get("positions", []), list) else []

    top_positions: list[dict[str, Any]] = []
    sorted_positions = sorted(
        [item for item in positions if isinstance(item, dict)],
        key=lambda x: float(x.get("market_value", 0.0) or 0.0),
        reverse=True,
    )
    for row in sorted_positions[:5]:
        top_positions.append(
            {
                "ticker": str(row.get("ticker", "")),
                "market_value": float(row.get("market_value", 0.0) or 0.0),
                "quantity": int(float(row.get("quantity", 0) or 0)),
            }
        )

    return {
        "account_id": str(account.get("account_id", "") or summary.get("account_id", "")),
        "currency": str(account.get("currency", "") or summary.get("currency", "")),
        "available_cash": float(summary.get("available_cash", 0.0) or 0.0),
        "total_assets": float(summary.get("total_assets", 0.0) or 0.0),
        "market_value": float(summary.get("market_value", 0.0) or 0.0),
        "positions_count": int(summary.get("positions_count", 0) or 0),
        "orders_count": int(summary.get("orders_count", 0) or 0),
        "trades_count": int(summary.get("trades_count", 0) or 0),
        "top_positions": top_positions,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="One-click THS easytrader setup + probe.")
    parser.add_argument("--exe-path", default=os.getenv("THS_EXE_PATH", DEFAULT_EXE_PATH))
    parser.add_argument("--broker", default=os.getenv("THS_EASYTRADER_BROKER", "ths"))
    parser.add_argument("--repo-path", default=os.getenv("EASYTRADER_REPO_PATH", ""))
    parser.add_argument("--grid-strategy", default=os.getenv("THS_EASYTRADER_GRID_STRATEGY", "auto"))
    parser.add_argument("--captcha-engine", default=os.getenv("THS_EASYTRADER_CAPTCHA_ENGINE", "auto"))
    parser.add_argument("--python32-path", default=os.getenv("THS_EASYTRADER_PYTHON32", ""))
    parser.add_argument("--skip-install", action="store_true")
    parser.add_argument("--no-pip-user", action="store_true")
    parser.add_argument("--no-include-orders", action="store_true")
    parser.add_argument("--no-include-trades", action="store_true")
    parser.add_argument("--probe-output", default=str(_default_probe_output()))
    parser.add_argument("--output", default=str(_default_output()))
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    args.exe_path = resolve_ths_exe_path(args.exe_path)
    repo_path = _to_existing_path(args.repo_path)
    python32 = _resolve_python32(args.python32_path)
    use_user = not bool(args.no_pip_user)
    include_orders = not bool(args.no_include_orders)
    include_trades = not bool(args.no_include_trades)

    report: dict[str, Any] = {
        "report_version": "1.0",
        "started_at": _iso_now(),
        "finished_at": "",
        "inputs": {
            "exe_path": args.exe_path,
            "broker": args.broker,
            "repo_path": repo_path,
            "grid_strategy": str(args.grid_strategy),
            "captcha_engine": str(args.captcha_engine),
            "python32_path_input": args.python32_path,
            "skip_install": bool(args.skip_install),
            "pip_user": use_user,
            "include_orders": include_orders,
            "include_trades": include_trades,
            "probe_output": str(_resolve(args.probe_output)),
        },
        "detection": {},
        "dependencies": {},
        "permission": {},
        "probe": {},
        "key_info": {},
        "hints": [],
        "ok": False,
    }

    detection = {
        "python32_path": python32,
        "python32_found": bool(python32),
        "python32_bits": _python_bits(python32) if python32 else 0,
        "current_python": sys.executable,
        "current_python_bits": _python_bits(sys.executable),
    }
    report["detection"] = detection

    runtime_current = inspect_easytrader_runtime(exe_path=args.exe_path)
    report["permission"]["current_runtime"] = runtime_current

    if not python32:
        report["hints"].append("未检测到 32 位 Python，请安装后设置 THS_EASYTRADER_PYTHON32。")
        return _finalize(report, args.output, ok=False)

    runtime_32 = _runtime_check_with_python(python32, args.exe_path)
    report["permission"]["python32_runtime"] = runtime_32

    deps_before = _check_dependencies(python32, repo_path)
    deps_need = list(deps_before.get("missing", []))
    if not deps_before.get("easytrader_ok", False) and not repo_path:
        deps_need.append("easytrader")
    deps_need = sorted({pkg for pkg in deps_need if pkg})

    install_result = {
        "before": deps_before,
        "need_install": deps_need,
    }
    if not args.skip_install and deps_need:
        install_result["install"] = _install_dependencies(python32, deps_need, use_user=use_user)
    else:
        install_result["install"] = {
            "ok": True,
            "skipped": True,
            "packages": deps_need,
            "returncode": 0,
            "stdout": "",
            "stderr": "",
        }
    deps_after = _check_dependencies(python32, repo_path)
    install_result["after"] = deps_after
    report["dependencies"] = install_result

    if not deps_after.get("ok", False):
        report["hints"].append("32 位 Python 依赖检查失败，请查看 dependencies.after.stderr。")
        return _finalize(report, args.output, ok=False)

    if deps_after.get("missing"):
        report["hints"].append(f"依赖仍缺失: {', '.join(deps_after['missing'])}")
        return _finalize(report, args.output, ok=False)

    probe_cmd = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "ths" / "run_easytrader_probe.py"),
        "--exe-path",
        args.exe_path,
        "--broker",
        args.broker,
        "--repo-path",
        repo_path,
        "--grid-strategy",
        str(args.grid_strategy),
        "--captcha-engine",
        str(args.captcha_engine),
        "--auto-delegate-32bit",
        "--python32-path",
        python32,
        "--output",
        str(_resolve(args.probe_output)),
    ]
    if include_orders:
        probe_cmd.append("--include-orders")
    if include_trades:
        probe_cmd.append("--include-trades")

    probe_exec = _run_cmd(probe_cmd, env=_merge_pythonpath([repo_path] if repo_path else []), timeout_s=300)
    report["probe"]["exec"] = probe_exec

    probe_file = _resolve(args.probe_output)
    probe_payload: dict[str, Any] = {}
    if probe_file.exists():
        try:
            probe_payload = json.loads(probe_file.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            report["hints"].append(f"读取 probe 报告失败: {exc}")
    report["probe"]["report_path"] = str(probe_file)
    report["probe"]["payload"] = probe_payload

    if probe_payload:
        report["key_info"] = _extract_key_info(probe_payload)

    ok = bool(probe_payload.get("probe", {}).get("ok", False)) if isinstance(probe_payload.get("probe", {}), dict) else False
    if not ok:
        report["hints"].append("自动复测未通过，请先对齐权限级别（来财与 xiadan）后重试。")
    return _finalize(report, args.output, ok=ok)


def _to_existing_path(path_like: str) -> str:
    text = str(path_like or "").strip()
    if not text:
        candidate = PROJECT_ROOT.parent / "easytrader-master"
        return str(candidate) if candidate.exists() else ""
    path = Path(text).expanduser()
    if path.exists():
        return str(path)
    return ""


def _finalize(report: dict[str, Any], output: str, *, ok: bool) -> int:
    report["ok"] = bool(ok)
    report["finished_at"] = _iso_now()
    output_path = _resolve(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    key_info = report.get("key_info", {}) if isinstance(report.get("key_info", {}), dict) else {}
    print(f"[easytrader-setup] report={output_path}")
    print(
        "[easytrader-setup] ok={ok} account={account} assets={assets} cash={cash} positions={positions} orders={orders} trades={trades}".format(
            ok=bool(ok),
            account=key_info.get("account_id", ""),
            assets=key_info.get("total_assets", 0.0),
            cash=key_info.get("available_cash", 0.0),
            positions=key_info.get("positions_count", 0),
            orders=key_info.get("orders_count", 0),
            trades=key_info.get("trades_count", 0),
        )
    )
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
