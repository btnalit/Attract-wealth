from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.execution.ths_auto.easytrader_adapter import (  # noqa: E402
    inspect_easytrader_runtime,
    probe_easytrader_readiness,
    resolve_ths_exe_path,
)

DEFAULT_EXE_PATH = r"D:\同花顺软件\同花顺\xiadan.exe"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_output() -> Path:
    return PROJECT_ROOT / "data" / "smoke" / "reports" / "ths_easytrader_probe_latest.json"


def _resolve(path_like: str) -> Path:
    path = Path(path_like).expanduser()
    if path.is_absolute():
        return path
    return (PROJECT_ROOT / path).resolve()


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


def _ensure_easytrader_repo_on_path(repo_path: str) -> None:
    text = str(repo_path or "").strip()
    if not text:
        return
    path = Path(text).expanduser()
    if path.exists() and str(path) not in sys.path:
        sys.path.insert(0, str(path))


def _normalize_grid_strategy_name(value: str) -> str:
    text = str(value or "").strip().lower()
    if text in {"auto", "copy", "xls", "wmcopy"}:
        return text
    return "auto"


def _patch_easytrader_grid_strategy(repo_path: str, strategy: str) -> tuple[bool, str]:
    strategy_name = _normalize_grid_strategy_name(strategy)
    if strategy_name == "auto":
        return True, "auto"
    _ensure_easytrader_repo_on_path(repo_path)
    try:
        grid_mod = importlib.import_module("easytrader.grid_strategies")
        client_mod = importlib.import_module("easytrader.clienttrader")
        universal_mod = importlib.import_module("easytrader.universal_clienttrader")
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)

    class_name_map = {
        "copy": "Copy",
        "xls": "Xls",
        "wmcopy": "WMCopy",
    }
    cls_name = class_name_map.get(strategy_name, "")
    strategy_cls = getattr(grid_mod, cls_name, None)
    if strategy_cls is None:
        return False, f"unsupported_grid_strategy:{strategy_name}"

    try:
        client_mod.ClientTrader.grid_strategy = strategy_cls
        universal_mod.UniversalClientTrader.grid_strategy = strategy_cls
        return True, strategy_name
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _probe_has_captcha_error(report: dict[str, Any]) -> bool:
    probe = report.get("probe", {}) if isinstance(report.get("probe", {}), dict) else {}
    errors = probe.get("errors", []) if isinstance(probe.get("errors", []), list) else []
    text = " ".join(str(item or "") for item in errors).lower()
    if not text:
        return False
    tokens = ("tesseract", "pytesseract", "captcha", "verify code", "ocr")
    return any(token in text for token in tokens)


def _patch_easytrader_captcha_engine(repo_path: str, engine: str) -> tuple[bool, str]:
    engine_name = str(engine or "").strip().lower()
    if engine_name in {"", "auto"}:
        engine_name = "ddddocr"
    if engine_name != "ddddocr":
        return False, f"unsupported_captcha_engine:{engine_name}"

    _ensure_easytrader_repo_on_path(repo_path)
    try:
        captcha_mod = importlib.import_module("easytrader.utils.captcha")
        ddddocr_mod = importlib.import_module("ddddocr")
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)

    try:
        import io
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)

    ocr = ddddocr_mod.DdddOcr(show_ad=False)

    def _ocr_bytes(image_bytes: bytes) -> str:
        text = str(ocr.classification(image_bytes) or "").strip()
        return "".join(ch for ch in text if ch.isalnum())

    def _captcha_recognize(img_path: str) -> str:
        with open(img_path, "rb") as fp:
            return _ocr_bytes(fp.read())

    def _invoke_tesseract_to_recognize(img: Any) -> str:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return _ocr_bytes(buf.getvalue())

    try:
        captcha_mod.captcha_recognize = _captcha_recognize
        captcha_mod.invoke_tesseract_to_recognize = _invoke_tesseract_to_recognize
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
    return True, engine_name


def _build_worker_cmd(args: argparse.Namespace, python_exec: str) -> list[str]:
    cmd = [
        python_exec,
        str(Path(__file__).resolve()),
        "--worker-mode",
        "--exe-path",
        args.exe_path,
        "--broker",
        args.broker,
        "--repo-path",
        args.repo_path,
        "--grid-strategy",
        args.grid_strategy,
        "--captcha-engine",
        args.captcha_engine,
        "--output",
        args.output,
    ]
    if args.include_orders:
        cmd.append("--include-orders")
    if args.include_trades:
        cmd.append("--include-trades")
    if args.no_runtime_guard:
        cmd.append("--no-runtime-guard")
    if args.allow_64bit_python:
        cmd.append("--allow-64bit-python")
    if args.no_require_process_access:
        cmd.append("--no-require-process-access")
    return cmd


def _run_probe(args: argparse.Namespace) -> dict[str, Any]:
    exe_path = resolve_ths_exe_path(args.exe_path)
    requested_grid_strategy = _normalize_grid_strategy_name(args.grid_strategy)

    captcha_patch_applied, captcha_patch_detail = _patch_easytrader_captcha_engine(args.repo_path, args.captcha_engine)

    grid_patch_applied = False
    grid_patch_detail = "auto"
    if requested_grid_strategy != "auto":
        grid_patch_applied, grid_patch_detail = _patch_easytrader_grid_strategy(args.repo_path, requested_grid_strategy)

    runtime = inspect_easytrader_runtime(
        exe_path=exe_path,
        require_32bit_python=not bool(args.allow_64bit_python),
        require_process_access=not bool(args.no_require_process_access),
    )

    probe = probe_easytrader_readiness(
        exe_path=exe_path,
        broker=args.broker,
        repo_path=args.repo_path,
        include_orders=bool(args.include_orders),
        include_trades=bool(args.include_trades),
        runtime_guard=not bool(args.no_runtime_guard),
        require_32bit_python=not bool(args.allow_64bit_python),
        require_process_access=not bool(args.no_require_process_access),
    )

    retry_with_xls_triggered = False
    if requested_grid_strategy == "auto" and (not bool(probe.get("ok", False))) and _probe_has_captcha_error({"probe": probe}):
        patched, detail = _patch_easytrader_grid_strategy(args.repo_path, "xls")
        if patched:
            retry_with_xls_triggered = True
            probe = probe_easytrader_readiness(
                exe_path=exe_path,
                broker=args.broker,
                repo_path=args.repo_path,
                include_orders=bool(args.include_orders),
                include_trades=bool(args.include_trades),
                runtime_guard=not bool(args.no_runtime_guard),
                require_32bit_python=not bool(args.allow_64bit_python),
                require_process_access=not bool(args.no_require_process_access),
            )
            probe_meta = probe.get("meta", {}) if isinstance(probe.get("meta", {}), dict) else {}
            probe_meta["grid_strategy_retry"] = "xls"
            probe["meta"] = probe_meta
            grid_patch_applied = True
            grid_patch_detail = detail

    report: dict[str, Any] = {
        "report_version": "1.1",
        "started_at": _iso_now(),
        "inputs": {
            "exe_path": exe_path,
            "broker": args.broker,
            "repo_path": args.repo_path,
            "grid_strategy": requested_grid_strategy,
            "captcha_engine": str(args.captcha_engine or ""),
            "include_orders": bool(args.include_orders),
            "include_trades": bool(args.include_trades),
            "runtime_guard": not bool(args.no_runtime_guard),
            "require_32bit_python": not bool(args.allow_64bit_python),
            "require_process_access": not bool(args.no_require_process_access),
            "auto_delegate_32bit": bool(args.auto_delegate_32bit),
            "python32_path": args.python32_path,
        },
        "launcher": {
            "used_python": sys.executable,
            "delegated_to_python32": False,
            "python32_path": "",
            "worker_returncode": 0,
            "worker_mode": bool(args.worker_mode),
            "grid_strategy_patch_applied": grid_patch_applied,
            "grid_strategy_patch_detail": grid_patch_detail,
            "retry_with_xls_triggered": retry_with_xls_triggered,
            "captcha_patch_applied": captcha_patch_applied,
            "captcha_patch_detail": captcha_patch_detail,
        },
        "runtime": runtime,
        "probe": probe,
        "status": "PASS" if probe.get("ok", False) else "FAIL",
        "finished_at": _iso_now(),
    }
    return report


def _write_report(path_like: str, report: dict[str, Any]) -> Path:
    output = _resolve(path_like)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe THS easytrader connectivity and account snapshot.")
    parser.add_argument("--exe-path", default=os.getenv("THS_EXE_PATH", DEFAULT_EXE_PATH))
    parser.add_argument("--broker", default=os.getenv("THS_EASYTRADER_BROKER", "ths"))
    parser.add_argument("--repo-path", default=os.getenv("EASYTRADER_REPO_PATH", ""))
    parser.add_argument("--grid-strategy", default=os.getenv("THS_EASYTRADER_GRID_STRATEGY", "auto"))
    parser.add_argument("--captcha-engine", default=os.getenv("THS_EASYTRADER_CAPTCHA_ENGINE", "auto"))
    parser.add_argument("--include-orders", action="store_true")
    parser.add_argument("--include-trades", action="store_true")
    parser.add_argument("--output", default=str(_default_output()))
    parser.add_argument("--no-runtime-guard", action="store_true", help="Disable runtime guard checks before probe.")
    parser.add_argument("--allow-64bit-python", action="store_true", help="Do not enforce 32-bit Python for 32-bit xiadan.")
    parser.add_argument(
        "--no-require-process-access",
        action="store_true",
        help="Do not enforce process query permission check.",
    )
    parser.add_argument("--auto-delegate-32bit", action="store_true", help="Auto re-run probe with 32-bit Python when needed.")
    parser.add_argument("--python32-path", default="", help="Explicit 32-bit python.exe path.")
    parser.add_argument("--worker-mode", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    args.exe_path = resolve_ths_exe_path(args.exe_path)

    # Parent mode: auto delegate to 32-bit Python when runtime says 32-bit is required.
    if (
        not args.worker_mode
        and args.auto_delegate_32bit
        and not args.allow_64bit_python
    ):
        runtime = inspect_easytrader_runtime(
            exe_path=args.exe_path,
            require_32bit_python=True,
            require_process_access=not bool(args.no_require_process_access),
        )
        if bool(runtime.get("needs_32bit_python", False)) and int(runtime.get("python_bits", 64)) != 32:
            python32 = _resolve_python32(args.python32_path)
            if python32:
                cmd = _build_worker_cmd(args, python32)
                proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT), check=False)

                # Merge launcher metadata into worker report for traceability.
                output = _resolve(args.output)
                if output.exists():
                    report = json.loads(output.read_text(encoding="utf-8"))
                else:
                    report = {
                        "report_version": "1.1",
                        "started_at": _iso_now(),
                        "probe": {"ok": False, "errors": ["worker_report_missing"]},
                        "status": "FAIL",
                    }
                report["launcher"] = {
                    "used_python": sys.executable,
                    "delegated_to_python32": True,
                    "python32_path": python32,
                    "worker_returncode": int(proc.returncode),
                    "worker_mode": False,
                    "worker_command": cmd,
                }
                report["finished_at"] = _iso_now()
                _write_report(args.output, report)

                probe = report.get("probe", {}) if isinstance(report.get("probe", {}), dict) else {}
                summary = probe.get("summary", {}) if isinstance(probe.get("summary", {}), dict) else {}
                print(f"[easytrader-probe] output={output}")
                print(
                    "[easytrader-probe] delegated_32bit=true ok={ok} total_assets={assets} available={cash} positions={positions} trades={trades}".format(
                        ok=probe.get("ok", False),
                        assets=summary.get("total_assets", 0.0),
                        cash=summary.get("available_cash", 0.0),
                        positions=summary.get("positions_count", 0),
                        trades=summary.get("trades_count", 0),
                    )
                )
                return 0 if probe.get("ok", False) else 2

    report = _run_probe(args)

    # When auto-delegate requested but no 32-bit Python found, annotate hints for actionability.
    if (
        not args.worker_mode
        and args.auto_delegate_32bit
        and not args.allow_64bit_python
        and bool((report.get("runtime", {}) if isinstance(report.get("runtime", {}), dict) else {}).get("needs_32bit_python", False))
        and int((report.get("runtime", {}) if isinstance(report.get("runtime", {}), dict) else {}).get("python_bits", 64)) != 32
    ):
        runtime = report.get("runtime", {}) if isinstance(report.get("runtime", {}), dict) else {}
        hints = runtime.get("hints", []) if isinstance(runtime.get("hints", []), list) else []
        hints.append("未找到 32 位 Python，请安装后设置 THS_EASYTRADER_PYTHON32 或 --python32-path。")
        runtime["hints"] = hints
        report["runtime"] = runtime

    output = _write_report(args.output, report)
    probe = report.get("probe", {}) if isinstance(report.get("probe", {}), dict) else {}
    summary = probe.get("summary", {}) if isinstance(probe.get("summary", {}), dict) else {}
    print(f"[easytrader-probe] output={output}")
    print(
        "[easytrader-probe] ok={ok} total_assets={assets} available={cash} positions={positions} trades={trades}".format(
            ok=probe.get("ok", False),
            assets=summary.get("total_assets", 0.0),
            cash=summary.get("available_cash", 0.0),
            positions=summary.get("positions_count", 0),
            trades=summary.get("trades_count", 0),
        )
    )
    return 0 if probe.get("ok", False) else 2


if __name__ == "__main__":
    raise SystemExit(main())
