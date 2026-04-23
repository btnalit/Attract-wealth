from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import sys
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.execution.base import OrderSide
from src.execution.broker_factory import create_broker
from src.execution.ths_auto.easytrader_adapter import probe_easytrader_readiness


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, (datetime,)):
        return value.isoformat()
    enum_value = getattr(value, "value", None)
    if enum_value is not None:
        return enum_value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def _default_report_path(channel: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("data") / "smoke" / "reports" / f"{channel}_{stamp}.json"


def _detect_qmt_account() -> str:
    return os.getenv("QMT_ACCOUNT_ID", "").strip() or os.getenv("QMT_ACCOUNT", "").strip()


def _is_true(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _preflight(channel: str) -> tuple[bool, str, dict[str, Any]]:
    if channel == "simulation":
        return True, "simulation ready", {}

    if channel == "qmt":
        account = _detect_qmt_account()
        qmt_path = os.getenv("QMT_PATH", "")
        path_ok = Path(qmt_path).exists() if qmt_path else False
        try:
            from src.execution.qmt_broker import XT_AVAILABLE

            xt_available = bool(XT_AVAILABLE)
        except Exception:
            xt_available = False

        meta = {
            "account_configured": bool(account),
            "qmt_path": qmt_path,
            "qmt_path_exists": path_ok,
            "xtquant_available": xt_available,
        }
        if not account:
            return False, "missing QMT_ACCOUNT_ID/QMT_ACCOUNT", meta
        if not qmt_path:
            return False, "missing QMT_PATH", meta
        if not path_ok:
            return False, f"QMT_PATH not found: {qmt_path}", meta
        if not xt_available:
            return False, "xtquant not available", meta
        return True, "qmt preflight passed", meta

    if channel == "ths_ipc":
        host = os.getenv("THS_IPC_HOST", "127.0.0.1")
        port = int(os.getenv("THS_IPC_PORT", "8089"))
        meta = {"host": host, "port": port}
        try:
            with socket.create_connection((host, port), timeout=1.2):
                return True, "ths_ipc bridge reachable", meta
        except Exception as exc:  # noqa: BLE001
            if _is_true(os.getenv("THS_IPC_ENABLE_EASYTRADER_DIAG"), default=True):
                diag = probe_easytrader_readiness(
                    exe_path=os.getenv("THS_EXE_PATH", r"D:\同花顺软件\同花顺\xiadan.exe"),
                    broker=os.getenv("THS_EASYTRADER_BROKER", "ths"),
                    repo_path=os.getenv("EASYTRADER_REPO_PATH", ""),
                    include_orders=False,
                )
                meta["easytrader_diag"] = {
                    "ok": bool(diag.get("ok", False)),
                    "summary": diag.get("summary", {}),
                    "errors": diag.get("errors", []),
                }
                if diag.get("ok", False):
                    return False, f"ths_ipc bridge unavailable: {exc}; easytrader_ready=true", meta
            return False, f"ths_ipc bridge unavailable: {exc}", meta

    if channel == "ths_auto":
        exe_path = os.getenv("THS_EXE_PATH", r"D:\同花顺软件\同花顺\xiadan.exe")
        meta = {"ths_exe_path": exe_path, "ths_exe_exists": Path(exe_path).exists()}
        if not meta["ths_exe_exists"]:
            return False, f"THS_EXE_PATH not found: {exe_path}", meta
        retries = max(1, int(os.getenv("THS_EASYTRADER_PREFLIGHT_RETRIES", "3")))
        retry_interval_s = max(0.0, _to_float(os.getenv("THS_EASYTRADER_PREFLIGHT_RETRY_INTERVAL_S", "0.8")))
        attempts: list[dict[str, Any]] = []
        final_diag: dict[str, Any] = {}
        for idx in range(retries):
            diag = probe_easytrader_readiness(
                exe_path=exe_path,
                broker=os.getenv("THS_EASYTRADER_BROKER", "ths"),
                repo_path=os.getenv("EASYTRADER_REPO_PATH", ""),
                include_orders=False,
            )
            final_diag = diag if isinstance(diag, dict) else {}
            diag_meta = final_diag.get("meta", {}) if isinstance(final_diag.get("meta", {}), dict) else {}
            attempts.append(
                {
                    "attempt": idx + 1,
                    "ok": bool(final_diag.get("ok", False)),
                    "errors": final_diag.get("errors", []),
                    "summary": final_diag.get("summary", {}),
                    "read_diagnostics": diag_meta.get("read_diagnostics", {}),
                    "captcha_stats": diag_meta.get("captcha_stats", {}),
                }
            )
            if bool(final_diag.get("ok", False)):
                break
            if idx < retries - 1 and retry_interval_s > 0:
                time.sleep(retry_interval_s)

        meta["easytrader_diag_attempts"] = attempts
        final_meta = final_diag.get("meta", {}) if isinstance(final_diag.get("meta", {}), dict) else {}
        meta["easytrader_diag"] = {
            "ok": bool(final_diag.get("ok", False)),
            "summary": final_diag.get("summary", {}),
            "errors": final_diag.get("errors", []),
            "read_diagnostics": final_meta.get("read_diagnostics", {}),
            "captcha_stats": final_meta.get("captcha_stats", {}),
        }
        if final_diag.get("ok", False):
            return True, "ths_auto preflight passed", meta
        if _is_true(os.getenv("THS_AUTO_ALLOW_STUB"), default=False):
            return True, "ths_auto fallback stub enabled", meta
        return False, "ths_auto easytrader runtime unavailable", meta

    return False, f"unsupported channel: {channel}", {}


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    channel = args.channel.strip().lower()
    report: dict[str, Any] = {
        "report_version": "1.1",
        "channel": channel,
        "started_at": _iso_now(),
        "finished_at": "",
        "duration_ms": 0.0,
        "status": "FAIL",
        "checks": [],
        "snapshots": {},
        "preflight": {},
        "config": {
            "include_order_probe": bool(args.include_order_probe),
            "force_live_order": bool(args.force_live_order),
            "include_reconcile": bool(args.include_reconcile),
            "strict_preflight": bool(args.strict_preflight),
            "ticker": args.ticker,
            "price": args.price,
            "quantity": args.quantity,
            "side": args.side,
        },
    }

    started = time.perf_counter()
    broker = None
    preflight_skipped = False

    async def _record_check(name: str, coro):
        check_start = time.perf_counter()
        ok = False
        detail = ""
        payload: Any = None
        skipped = False
        try:
            payload = await coro()
            ok = True
            detail = "ok"
        except RuntimeError as exc:
            if str(exc).startswith("SKIP:"):
                skipped = True
                ok = True
                detail = str(exc)[5:].strip()
            else:
                detail = str(exc)
        except Exception as exc:  # noqa: BLE001
            detail = str(exc)

        report["checks"].append(
            {
                "name": name,
                "ok": ok,
                "skipped": skipped,
                "detail": detail,
                "elapsed_ms": round((time.perf_counter() - check_start) * 1000, 3),
            }
        )
        return ok, payload

    async def _check_preflight():
        nonlocal preflight_skipped
        ready, reason, metadata = _preflight(channel)
        report["preflight"] = {"ready": ready, "reason": reason, "metadata": metadata}
        if ready:
            return report["preflight"]
        if args.strict_preflight:
            raise RuntimeError(f"preflight failed: {reason}")
        preflight_skipped = True
        raise RuntimeError(f"SKIP: preflight skipped ({reason})")

    async def _check_connect():
        assert broker is not None
        connected = await broker.connect()
        if not connected:
            raise RuntimeError("broker connect failed")
        return {"connected": connected}

    async def _check_balance():
        assert broker is not None
        return await broker.get_balance()

    async def _check_positions():
        assert broker is not None
        return await broker.get_positions()

    async def _check_orders():
        assert broker is not None
        return await broker.get_orders()

    async def _check_reconcile():
        if not args.include_reconcile:
            raise RuntimeError("SKIP: reconcile probe disabled")
        from src.execution.reconciliation import ReconciliationEngine

        assert broker is not None
        balance = await broker.get_balance()
        initial_cash = _resolve_reconcile_initial_cash(
            channel=channel,
            balance=balance,
            explicit_initial_cash=args.reconcile_initial_cash,
        )
        bootstrap_meta = _bootstrap_simulation_broker_from_ledger(
            broker=broker,
            initial_cash=initial_cash,
        )
        if bootstrap_meta.get("applied", False):
            report["snapshots"]["reconcile_bootstrap"] = bootstrap_meta
        engine = ReconciliationEngine(broker=broker)
        recon = await engine.run(initial_cash=initial_cash)
        if recon.get("code") in {"RECON_BLOCK", "RECON_ERROR"}:
            raise RuntimeError(f"reconciliation failed: {recon.get('code')}")
        return recon

    async def _check_order_probe():
        if not args.include_order_probe:
            raise RuntimeError("SKIP: order probe disabled")
        if channel != "simulation":
            allow_flag = os.getenv("SMOKE_ALLOW_LIVE_ORDER", "").strip().lower() == "true"
            if not (args.force_live_order and allow_flag):
                raise RuntimeError("SKIP: live order probe requires --force-live-order and SMOKE_ALLOW_LIVE_ORDER=true")

        assert broker is not None
        side = OrderSide.BUY if args.side == "BUY" else OrderSide.SELL
        if side == OrderSide.BUY:
            result = await broker.buy(args.ticker, args.price, args.quantity)
        else:
            result = await broker.sell(args.ticker, args.price, args.quantity)
        return result

    try:
        preflight_ok, _ = await _record_check("preflight", _check_preflight)
        if preflight_skipped:
            report["status"] = "SKIP"
            return report
        if not preflight_ok:
            report["status"] = "FAIL"
            return report

        broker = create_broker(channel)
        connect_ok, _ = await _record_check("connect", _check_connect)
        if connect_ok:
            _, balance = await _record_check("get_balance", _check_balance)
            report["snapshots"]["balance"] = _json_safe(balance)
            _, positions = await _record_check("get_positions", _check_positions)
            report["snapshots"]["positions"] = _json_safe(positions)
            _, orders = await _record_check("get_orders", _check_orders)
            report["snapshots"]["orders"] = _json_safe(orders)
            _, recon = await _record_check("reconciliation_probe", _check_reconcile)
            if recon is not None:
                report["snapshots"]["reconciliation"] = _json_safe(recon)
            _, order_probe = await _record_check("order_probe", _check_order_probe)
            if order_probe is not None:
                report["snapshots"]["order_probe"] = _json_safe(order_probe)
    finally:
        if broker is not None:
            try:
                await broker.disconnect()
            except Exception:  # noqa: BLE001
                pass

    report["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
    report["finished_at"] = _iso_now()

    if preflight_skipped:
        report["status"] = "SKIP"
        return report

    has_failed_required_check = any((not item["ok"]) for item in report["checks"] if not item.get("skipped"))
    report["status"] = "PASS" if not has_failed_required_check else "FAIL"
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Live channel smoke test for THS/QMT/Simulation.")
    parser.add_argument("--channel", required=True, choices=["simulation", "ths_ipc", "ths_auto", "qmt"])
    parser.add_argument("--include-order-probe", action="store_true", help="Probe buy/sell path (disabled by default).")
    parser.add_argument(
        "--force-live-order",
        action="store_true",
        help="Allow real-channel order probe only when SMOKE_ALLOW_LIVE_ORDER=true.",
    )
    parser.add_argument("--include-reconcile", action="store_true", help="Run reconciliation probe after snapshot.")
    parser.add_argument("--strict-preflight", action="store_true", help="Fail instead of skip when preflight not ready.")
    parser.add_argument("--ticker", default=os.getenv("SMOKE_TICKER", "000001"))
    parser.add_argument("--price", type=float, default=float(os.getenv("SMOKE_PRICE", "10")))
    parser.add_argument("--quantity", type=int, default=int(os.getenv("SMOKE_QUANTITY", "100")))
    parser.add_argument("--side", choices=["BUY", "SELL"], default=os.getenv("SMOKE_SIDE", "BUY").upper())
    parser.add_argument(
        "--reconcile-initial-cash",
        type=float,
        default=None,
        help="Optional reconciliation initial cash override. Defaults to broker snapshot cash/asset baseline.",
    )
    parser.add_argument("--output", default="", help="Output report path. Defaults to data/smoke/reports/<channel>_<time>.json")
    return parser.parse_args()


def _resolve_reconcile_initial_cash(*, channel: str, balance: Any, explicit_initial_cash: float | None) -> float:
    if explicit_initial_cash is not None:
        return float(explicit_initial_cash)

    total_assets = float(getattr(balance, "total_assets", 0.0) or 0.0)
    available_cash = float(getattr(balance, "available_cash", 0.0) or 0.0)
    baseline = max(total_assets, available_cash, 0.0)
    if baseline > 0:
        return baseline

    if str(channel or "").strip().lower() == "simulation":
        return 1_000_000.0
    return 0.0


def _bootstrap_simulation_broker_from_ledger(*, broker: Any, initial_cash: float) -> dict[str, Any]:
    """
    对齐 simulation 通道 broker 与 ledger 的历史快照口径，避免进程重启导致的假阳性阻断。
    """
    channel_name = str(getattr(broker, "channel_name", "") or "").strip().lower()
    if channel_name != "simulation":
        return {"applied": False, "reason": "non_simulation"}
    if not _is_true(os.getenv("SMOKE_SIM_RECON_BOOTSTRAP", "true"), default=True):
        return {"applied": False, "reason": "disabled"}
    if not hasattr(broker, "load_portfolio_snapshot"):
        return {"applied": False, "reason": "broker_without_snapshot_loader"}

    from src.core.trading_ledger import TradingLedger

    snapshot = TradingLedger.build_portfolio_snapshot(initial_cash=float(initial_cash), channel=channel_name)
    cash = float(snapshot.get("cash", initial_cash) or initial_cash)
    positions = snapshot.get("positions", {})
    if not isinstance(positions, dict):
        positions = {}

    broker.load_portfolio_snapshot(
        cash=cash,
        positions={str(k): int(v or 0) for k, v in positions.items()},
        reset_orders=True,
    )
    return {
        "applied": True,
        "channel": channel_name,
        "initial_cash": float(initial_cash),
        "snapshot_cash": cash,
        "positions_count": len([v for v in positions.values() if int(v or 0) > 0]),
    }


def main() -> int:
    args = _parse_args()
    report = asyncio.run(_run(args))

    output_path = Path(args.output).expanduser() if args.output else _default_report_path(args.channel)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[smoke] status={report['status']} channel={report['channel']} output={output_path}")
    for check in report["checks"]:
        print(
            f"[smoke] check={check['name']} ok={check['ok']} skipped={check['skipped']} "
            f"elapsed_ms={check['elapsed_ms']} detail={check['detail']}"
        )
    return 0 if report["status"] in {"PASS", "SKIP"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
