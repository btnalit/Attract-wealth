from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.ths_host_autostart import (  # noqa: E402
    analyze_host_trigger_chain,
    collect_xiadan_ui_context,
    collect_host_observability_snapshot,
    DEFAULT_THS_ROOT,
    fetch_trade_snapshot,
    is_xiadan_running,
    probe_bridge_runtime,
    read_ths_account_context,
    summarize_trade_snapshot,
)
from src.execution.ths_auto.easytrader_adapter import probe_easytrader_readiness  # noqa: E402


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_report_path() -> Path:
    return PROJECT_ROOT / "data" / "smoke" / "reports" / "ths_host_runtime_probe_latest.json"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe THS IPC host runtime readiness.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8089)
    parser.add_argument("--ths-root", default=str(DEFAULT_THS_ROOT))
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--interval-seconds", type=float, default=1.0)
    parser.add_argument("--report-output", default=str(_default_report_path()))
    parser.add_argument("--allow-mock", action="store_true")
    parser.add_argument("--no-snapshot", action="store_true")
    parser.add_argument("--require-snapshot", action="store_true")
    parser.add_argument("--no-require-xiadan-process", action="store_true")
    parser.add_argument("--no-easytrader-diag", action="store_true")
    parser.add_argument("--easytrader-repo", default=os.getenv("EASYTRADER_REPO_PATH", ""))
    parser.add_argument("--easytrader-broker", default=os.getenv("THS_EASYTRADER_BROKER", "ths"))
    parser.add_argument("--easytrader-exe-path", default=os.getenv("THS_EXE_PATH", r"D:\同花顺软件\同花顺\xiadan.exe"))
    parser.add_argument("--easytrader-grid-strategy", default=os.getenv("THS_EASYTRADER_GRID_STRATEGY", "auto"))
    parser.add_argument("--easytrader-captcha-engine", default=os.getenv("THS_EASYTRADER_CAPTCHA_ENGINE", "auto"))
    parser.add_argument("--easytrader-include-orders", action="store_true")
    parser.add_argument("--easytrader-include-trades", action="store_true")
    parser.add_argument("--easytrader-no-runtime-guard", action="store_true")
    parser.add_argument("--easytrader-allow-64bit-python", action="store_true")
    parser.add_argument("--easytrader-no-require-process-access", action="store_true")
    return parser.parse_args()


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


def _resolve_path(path_like: str) -> Path:
    path = Path(path_like).expanduser()
    if path.is_absolute():
        return path
    return (PROJECT_ROOT / path).resolve()


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    started_at = _iso_now()
    deadline = time.time() + max(1.0, float(args.timeout_seconds))
    interval = max(0.2, float(args.interval_seconds))
    require_xiadan = not args.no_require_xiadan_process
    xiadan_running, xiadan_check_error = _is_xiadan_running()
    xiadan_known = xiadan_running is not None

    report: dict[str, Any] = {
        "report_version": "1.2",
        "started_at": started_at,
        "finished_at": "",
        "inputs": {
            "host": args.host,
            "port": int(args.port),
            "timeout_seconds": float(args.timeout_seconds),
            "interval_seconds": interval,
            "allow_mock": bool(args.allow_mock),
            "enable_snapshot": not bool(args.no_snapshot),
            "require_snapshot": bool(args.require_snapshot),
            "require_xiadan_process": require_xiadan,
            "ths_root": str(args.ths_root),
            "enable_easytrader_diag": not bool(args.no_easytrader_diag),
            "easytrader_repo": str(args.easytrader_repo),
            "easytrader_broker": str(args.easytrader_broker),
            "easytrader_exe_path": str(args.easytrader_exe_path),
            "easytrader_grid_strategy": str(args.easytrader_grid_strategy),
            "easytrader_captcha_engine": str(args.easytrader_captcha_engine),
            "easytrader_include_orders": bool(args.easytrader_include_orders),
            "easytrader_include_trades": bool(args.easytrader_include_trades),
            "easytrader_runtime_guard": not bool(args.easytrader_no_runtime_guard),
            "easytrader_require_32bit_python": not bool(args.easytrader_allow_64bit_python),
            "easytrader_require_process_access": not bool(args.easytrader_no_require_process_access),
        },
        "xiadan_running": xiadan_running,
        "xiadan_process_check": {
            "known": xiadan_known,
            "error": xiadan_check_error,
        },
        "xiadan_ui_context": collect_xiadan_ui_context(),
        "account_context": read_ths_account_context(Path(str(args.ths_root))),
        "host_observability": collect_host_observability_snapshot(Path(str(args.ths_root))),
        "samples": [],
        "status": "FAIL",
        "ready": False,
        "runtime_ok": False,
        "snapshot": {},
        "snapshot_summary": {},
        "snapshot_ok": False,
        "easytrader_diag": {},
        "easytrader_patch": {},
        "host_trigger_diagnosis": {},
        "hints": [],
    }

    host_observability = report.get("host_observability", {}) if isinstance(report.get("host_observability", {}), dict) else {}
    host_execution_evidence = bool(host_observability.get("host_execution_evidence", False))
    host_has_errors = bool(host_observability.get("has_errors", False))
    if not host_execution_evidence:
        report["hints"].append("未检测到 my_signals/bootstrap 执行标记，请在 THS 交易会话中触发策略条件单脚本。")
    if host_has_errors:
        report["hints"].append("检测到宿主脚本异常持久化日志，请查看 host_observability.*.error_tail。")

    if require_xiadan and xiadan_known and not bool(report["xiadan_running"]):
        report["hints"].append("未检测到 xiadan.exe 进程，请先登录同花顺交易客户端。")
    elif require_xiadan and not xiadan_known:
        report["hints"].append("无法读取 xiadan.exe 进程状态（权限受限），将继续按 runtime 探针判定。")
    xiadan_ui_context = report.get("xiadan_ui_context", {}) if isinstance(report.get("xiadan_ui_context", {}), dict) else {}
    if bool(xiadan_ui_context.get("running", False)) and not bool(xiadan_ui_context.get("strategy_page_open", False)):
        report["hints"].append("检测到 xiadan 会话，但未发现“策略条件单/信号策略”窗口。")

    last_sample: dict[str, Any] = {}
    while time.time() < deadline:
        sample = probe_bridge_runtime(host=args.host, port=args.port, timeout_s=1.2)
        sample["sample_at"] = _iso_now()
        report["samples"].append(sample)
        last_sample = sample

        if sample.get("reachable", False):
            runtime_ok = bool(sample.get("runtime_ok", False))
            if runtime_ok or args.allow_mock:
                report["ready"] = True
                report["runtime_ok"] = runtime_ok
                report["status"] = "PASS" if runtime_ok else "WARN"
                break
        time.sleep(interval)

    if not report["ready"]:
        report["status"] = "FAIL"
        report["runtime_ok"] = bool(last_sample.get("runtime_ok", False))
        if last_sample.get("reachable", False):
            report["hints"].append("检测到 8089 端口可达，但 runtime 不是 THS 宿主。")
        else:
            report["hints"].append("未检测到 THS IPC bridge 监听 8089，请确认宿主自动脚本已加载。")
        report["hints"].append("请在同花顺中打开一次“策略条件单/信号策略”触发 my_signals.py 加载后再重试。")
        if host_execution_evidence:
            report["hints"].append("已检测到宿主脚本执行标记，当前阻塞更可能在 bridge 启动或 runtime 初始化阶段。")
    elif not args.no_snapshot:
        snapshot = fetch_trade_snapshot(host=args.host, port=args.port, timeout_s=2.0)
        summary = summarize_trade_snapshot(snapshot)
        report["snapshot"] = snapshot
        report["snapshot_summary"] = summary

        snapshot_ok = bool(snapshot.get("ok", False)) and summary.get("snapshot_status") == "success"
        report["snapshot_ok"] = snapshot_ok

        if args.require_snapshot and not snapshot_ok:
            report["status"] = "FAIL"
            report["hints"].append("runtime 已就绪，但交易快照拉取失败（require_snapshot=true）。")
        elif not snapshot_ok:
            report["status"] = "WARN"
            report["hints"].append("runtime 已就绪，但 get_trade_snapshot 未返回 success。")
        elif not bool(summary.get("has_balance", False)):
            report["status"] = "WARN"
            report["hints"].append("已连通宿主，但资金字段为空，请在交易客户端确认账户页已初始化。")

    if not args.no_easytrader_diag:
        grid_patch_ok, grid_patch_detail = _patch_easytrader_grid_strategy(
            args.easytrader_repo,
            args.easytrader_grid_strategy,
        )
        captcha_patch_ok, captcha_patch_detail = _patch_easytrader_captcha_engine(
            args.easytrader_repo,
            args.easytrader_captcha_engine,
        )
        report["easytrader_patch"] = {
            "grid": {
                "ok": bool(grid_patch_ok),
                "detail": str(grid_patch_detail),
            },
            "captcha": {
                "ok": bool(captcha_patch_ok),
                "detail": str(captcha_patch_detail),
            },
        }

        diag = probe_easytrader_readiness(
            exe_path=args.easytrader_exe_path,
            broker=args.easytrader_broker,
            repo_path=args.easytrader_repo,
            include_orders=bool(args.easytrader_include_orders),
            include_trades=bool(args.easytrader_include_trades),
            runtime_guard=not bool(args.easytrader_no_runtime_guard),
            require_32bit_python=not bool(args.easytrader_allow_64bit_python),
            require_process_access=not bool(args.easytrader_no_require_process_access),
        )
        report["easytrader_diag"] = {
            "ok": bool(diag.get("ok", False)),
            "summary": diag.get("summary", {}),
            "errors": diag.get("errors", []),
            "meta": diag.get("meta", {}),
            "runtime": diag.get("runtime", {}),
        }
        if report["status"] == "FAIL" and bool(diag.get("ok", False)):
            report["hints"].append("easytrader 可读资金/持仓，说明交易端可接入；当前主要阻塞在 THS 宿主 bridge 未加载。")
        elif report["status"] in {"FAIL", "WARN"} and not bool(diag.get("ok", False)):
            report["hints"].append("easytrader 诊断也失败，需先排查 xiadan 进程会话、依赖和权限。")

    report["host_trigger_diagnosis"] = analyze_host_trigger_chain(
        report.get("host_observability", {}),
        xiadan_running=xiadan_running,
        runtime_probe=last_sample,
        ui_context=xiadan_ui_context,
    )
    diagnosis = (
        report.get("host_trigger_diagnosis", {})
        if isinstance(report.get("host_trigger_diagnosis", {}), dict)
        else {}
    )
    for hint in diagnosis.get("suggestions", []) if isinstance(diagnosis.get("suggestions", []), list) else []:
        text = str(hint or "").strip()
        if text and text not in report["hints"]:
            report["hints"].append(text)

    report["finished_at"] = _iso_now()
    return report


def main() -> int:
    args = _parse_args()
    report = run_probe(args)
    output = _resolve_path(args.report_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[ths-host-probe] report={output}")
    print(
        "[ths-host-probe] status={status} ready={ready} runtime_ok={runtime_ok} snapshot_ok={snapshot_ok}".format(
            status=report.get("status", ""),
            ready=report.get("ready", False),
            runtime_ok=report.get("runtime_ok", False),
            snapshot_ok=report.get("snapshot_ok", False),
        )
    )

    account_ctx = report.get("account_context", {}) if isinstance(report.get("account_context", {}), dict) else {}
    if account_ctx:
        print(
            "[ths-host-probe] account={name} userid={userid} mode_hint={mode}".format(
                name=account_ctx.get("last_user_name", ""),
                userid=account_ctx.get("last_userid", ""),
                mode=account_ctx.get("mode_hint", "unknown"),
            )
        )

    host_obs = report.get("host_observability", {}) if isinstance(report.get("host_observability", {}), dict) else {}
    if host_obs:
        my_obs = host_obs.get("my_signals", {}) if isinstance(host_obs.get("my_signals", {}), dict) else {}
        bootstrap_obs = host_obs.get("bootstrap", {}) if isinstance(host_obs.get("bootstrap", {}), dict) else {}
        print(
            "[ths-host-probe] host_obs evidence={evidence} errors={errors} my_markers={my_count} bootstrap_markers={bootstrap_count}".format(
                evidence=host_obs.get("host_execution_evidence", False),
                errors=host_obs.get("has_errors", False),
                my_count=my_obs.get("marker_count", 0),
                bootstrap_count=bootstrap_obs.get("marker_count", 0),
            )
        )
    xiadan_ui = report.get("xiadan_ui_context", {}) if isinstance(report.get("xiadan_ui_context", {}), dict) else {}
    if xiadan_ui:
        titles = xiadan_ui.get("window_titles", []) if isinstance(xiadan_ui.get("window_titles", []), list) else []
        print(
            "[ths-host-probe] xiadan_ui running={running} strategy_page_open={strategy} windows={count}".format(
                running=xiadan_ui.get("running", False),
                strategy=xiadan_ui.get("strategy_page_open", False),
                count=len(titles),
            )
        )
    trigger_diag = report.get("host_trigger_diagnosis", {}) if isinstance(report.get("host_trigger_diagnosis", {}), dict) else {}
    if trigger_diag:
        print(
            "[ths-host-probe] trigger_stage={stage} trigger_status={status}".format(
                stage=trigger_diag.get("stage", "UNKNOWN"),
                status=trigger_diag.get("status", "FAIL"),
            )
        )

    summary = report.get("snapshot_summary", {}) if isinstance(report.get("snapshot_summary", {}), dict) else {}
    if summary:
        print(
            "[ths-host-probe] balance={has_balance} positions={positions} open_orders={open_orders}".format(
                has_balance=summary.get("has_balance", False),
                positions=summary.get("positions_count", 0),
                open_orders=summary.get("open_orders_count", 0),
            )
        )

    easy_diag = report.get("easytrader_diag", {}) if isinstance(report.get("easytrader_diag", {}), dict) else {}
    easy_patch = report.get("easytrader_patch", {}) if isinstance(report.get("easytrader_patch", {}), dict) else {}
    if easy_patch:
        grid_patch = easy_patch.get("grid", {}) if isinstance(easy_patch.get("grid", {}), dict) else {}
        captcha_patch = easy_patch.get("captcha", {}) if isinstance(easy_patch.get("captcha", {}), dict) else {}
        print(
            "[ths-host-probe] easytrader_patch grid_ok={grid_ok} captcha_ok={captcha_ok}".format(
                grid_ok=grid_patch.get("ok", False),
                captcha_ok=captcha_patch.get("ok", False),
            )
        )
    if easy_diag:
        print(
            "[ths-host-probe] easytrader_ok={ok} positions={positions} orders={orders} trades={trades}".format(
                ok=easy_diag.get("ok", False),
                positions=(easy_diag.get("summary", {}) if isinstance(easy_diag.get("summary", {}), dict) else {}).get(
                    "positions_count", 0
                ),
                orders=(easy_diag.get("summary", {}) if isinstance(easy_diag.get("summary", {}), dict) else {}).get(
                    "orders_count", 0
                ),
                trades=(easy_diag.get("summary", {}) if isinstance(easy_diag.get("summary", {}), dict) else {}).get(
                    "trades_count", 0
                ),
            )
        )

    return 0 if report.get("status") in {"PASS", "WARN"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
