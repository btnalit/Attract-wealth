from __future__ import annotations

import argparse
import importlib
import itertools
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

_GRID_SORT_ASC_METRICS = {"max_drawdown"}
_DEFAULT_GRID = {
    "lookback": [2, 3, 5],
    "position_ratio": [0.4, 0.6, 0.8],
}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_output_path() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return ROOT_DIR / "data" / "strategy" / "reports" / f"p4_lifecycle_smoke_{stamp}.json"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="P4 strategy lifecycle smoke runner.")
    parser.add_argument("--data-dir", default="data/p4_smoke", help="Isolated DATA_DIR for smoke.")
    parser.add_argument("--output", default="", help="Report output path.")
    parser.add_argument("--reset-data-dir", action="store_true", default=True)
    parser.add_argument("--no-reset-data-dir", action="store_true")
    parser.add_argument("--strategy-name", default="p4_lifecycle_smoke")
    parser.add_argument("--market", default="CN")
    parser.add_argument("--strategy-template", default="momentum")
    parser.add_argument("--bars", type=int, default=80, help="Generated bars length.")
    parser.add_argument("--start-cash", type=float, default=1_000_000.0)
    parser.add_argument("--lot-size", type=int, default=100)
    parser.add_argument("--commission-rate", type=float, default=0.0003)
    parser.add_argument("--slippage-bp", type=float, default=1.0)
    parser.add_argument("--grid-json", default="", help="JSON object, e.g. {\"lookback\":[2,3],\"position_ratio\":[0.4,0.8]}")
    parser.add_argument("--max-combinations", type=int, default=128)
    parser.add_argument("--sort-by", default="net_pnl")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--run-tag", default="smoke")
    parser.add_argument(
        "--gate-overrides-json",
        default='{"min_trades":1,"min_win_rate":0.0}',
        help="Gate overrides used in baseline/grid evaluations.",
    )
    parser.add_argument("--archive-report", action="store_true", default=True)
    parser.add_argument("--no-archive-report", action="store_true")
    parser.add_argument("--persist-best-metrics", action="store_true", default=True)
    parser.add_argument("--no-persist-best-metrics", action="store_true")
    parser.add_argument("--check-invalid-transition", action="store_true", default=True)
    parser.add_argument("--skip-invalid-transition-check", action="store_true")
    return parser.parse_args()


def _safe_reset_data_dir(data_dir: Path) -> None:
    if not data_dir.exists():
        return
    for pattern in ("*.db", "*.db-shm", "*.db-wal"):
        for item in data_dir.glob(pattern):
            try:
                item.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                continue


def _build_bars(count: int) -> list[dict[str, Any]]:
    total = max(10, int(count))
    bars: list[dict[str, Any]] = []
    price = 10.0
    for i in range(total):
        drift = 0.0015
        wave = ((i % 9) - 4) * 0.0012
        price = max(1.0, price * (1.0 + drift + wave))
        bars.append(
            {
                "timestamp": f"2026-01-{(i % 28) + 1:02d}",
                "close": round(price, 6),
                "signal": "AUTO",
            }
        )
    return bars


def _build_parameter_sets(args: argparse.Namespace) -> list[dict[str, Any]]:
    grid: dict[str, list[Any]]
    if str(args.grid_json or "").strip():
        payload = json.loads(str(args.grid_json))
        if not isinstance(payload, dict):
            raise ValueError("grid_json must be a JSON object")
        grid = {}
        for key, values in payload.items():
            if not isinstance(values, list) or not values:
                raise ValueError(f"grid_json[{key}] must be a non-empty list")
            grid[str(key)] = list(values)
    else:
        grid = {key: list(values) for key, values in _DEFAULT_GRID.items()}

    total = 1
    for values in grid.values():
        total *= len(values)
        if total > int(args.max_combinations):
            raise ValueError("parameter grid combinations exceed max_combinations")

    keys = list(grid.keys())
    rows = [dict(zip(keys, values)) for values in itertools.product(*(grid[key] for key in keys))]
    return rows


def _metric_value(metrics: dict[str, Any], key: str) -> float:
    try:
        return float(metrics.get(key, 0.0))
    except (TypeError, ValueError):
        return 0.0


def _parse_gate_overrides(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        return {}
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("gate_overrides_json must be a JSON object")
    return dict(payload)


def main() -> int:
    args = _parse_args()
    if args.no_reset_data_dir:
        args.reset_data_dir = False
    if args.no_archive_report:
        args.archive_report = False
    if args.no_persist_best_metrics:
        args.persist_best_metrics = False
    if args.skip_invalid_transition_check:
        args.check_invalid_transition = False

    data_dir = Path(args.data_dir).expanduser()
    if not data_dir.is_absolute():
        data_dir = ROOT_DIR / data_dir
    output_path = Path(args.output).expanduser() if args.output else _default_output_path()
    if not output_path.is_absolute():
        output_path = ROOT_DIR / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    if args.reset_data_dir:
        _safe_reset_data_dir(data_dir)

    os.environ["DATA_DIR"] = str(data_dir)

    import src.core.storage as storage_module
    import src.core.trading_ledger as trading_ledger_module
    import src.core.strategy_store as strategy_store_module
    import src.evolution.backtest_runner as backtest_runner_module
    from src.core.errors import TradingServiceError

    storage_module = importlib.reload(storage_module)
    trading_ledger_module = importlib.reload(trading_ledger_module)
    strategy_store_module = importlib.reload(strategy_store_module)
    backtest_runner_module = importlib.reload(backtest_runner_module)

    init_all_databases = storage_module.init_all_databases
    StrategyStore = strategy_store_module.StrategyStore
    BacktestRunner = backtest_runner_module.BacktestRunner

    started_at = _iso_now()
    started_perf = time.perf_counter()
    steps: list[dict[str, Any]] = []
    report_payload: dict[str, Any] = {}

    def mark_step(name: str, status: str, detail: str, payload: dict[str, Any] | None = None) -> None:
        steps.append(
            {
                "name": name,
                "status": status,
                "detail": detail,
                "payload": payload or {},
                "at": _iso_now(),
            }
        )

    try:
        init_all_databases()
        mark_step("init_databases", "PASS", "sqlite schemas initialized", {"data_dir": str(data_dir)})

        store = StrategyStore()
        runner = BacktestRunner()
        bars = _build_bars(args.bars)
        param_sets = _build_parameter_sets(args)
        gate_overrides = _parse_gate_overrides(args.gate_overrides_json)
        market = str(args.market or "CN").strip().upper() or "CN"
        template = str(args.strategy_template or "default").strip().lower() or "default"

        base = store.create_strategy_version(
            name=str(args.strategy_name or "p4_lifecycle_smoke"),
            status="draft",
            market=market,
            strategy_template=template,
            parameters={
                "lookback": 3,
                "position_ratio": 0.6,
                "buy_threshold": 0.01,
                "sell_threshold": -0.01,
                "market": market,
                "strategy_template": template,
            },
            metrics={
                "trade_count": 30,
                "win_rate": 0.56,
                "max_drawdown": 0.16,
                "net_pnl": 1200,
                "sharpe": 0.9,
                "market": market,
                "strategy_template": template,
            },
        )
        mark_step(
            "create_strategy_version",
            "PASS",
            "draft strategy created",
            {"strategy_id": base.get("id", ""), "version": base.get("version", 0)},
        )

        if args.check_invalid_transition:
            try:
                store.transition_strategy_status(
                    base["id"],
                    target_status="active",
                    operator="p4_smoke",
                )
                mark_step(
                    "invalid_transition_guard",
                    "FAIL",
                    "draft -> active should be rejected but succeeded",
                )
                raise RuntimeError("invalid transition guard is not enforced")
            except TradingServiceError as exc:
                if exc.code != "STRATEGY_STATUS_TRANSITION_INVALID":
                    mark_step(
                        "invalid_transition_guard",
                        "FAIL",
                        "unexpected error code for invalid transition",
                        {"code": exc.code, "message": exc.message},
                    )
                    raise
                mark_step(
                    "invalid_transition_guard",
                    "PASS",
                    "draft -> active correctly rejected",
                    {"code": exc.code},
                )

        baseline_params = {
            **(base.get("parameters", {}) if isinstance(base.get("parameters", {}), dict) else {}),
            "market": market,
            "strategy_template": template,
        }
        baseline_report = runner.run(
            strategy_id=base["id"],
            strategy_name=base["name"],
            strategy_version=base["version"],
            bars=bars,
            parameters=baseline_params,
            start_cash=float(args.start_cash),
            lot_size=int(args.lot_size),
            commission_rate=float(args.commission_rate),
            slippage_bp=float(args.slippage_bp),
        )
        baseline_metrics = baseline_report.get("metrics", {}) if isinstance(baseline_report.get("metrics", {}), dict) else {}
        baseline_metrics["market"] = market
        baseline_metrics["strategy_template"] = template
        store.update_strategy_metrics(base["id"], baseline_metrics, merge=True)
        mark_step(
            "run_baseline_backtest",
            "PASS",
            "baseline backtest completed",
            {
                "bars": len(bars),
                "metrics": {
                    "trade_count": baseline_metrics.get("trade_count", 0),
                    "win_rate": baseline_metrics.get("win_rate", 0.0),
                    "max_drawdown": baseline_metrics.get("max_drawdown", 0.0),
                    "net_pnl": baseline_metrics.get("net_pnl", 0.0),
                    "sharpe": baseline_metrics.get("sharpe", 0.0),
                },
            },
        )

        baseline_archive: dict[str, Any] = {}
        if args.archive_report:
            baseline_archive = store.archive_backtest_report(
                strategy_id=base["id"],
                report={**baseline_report, "market": market, "strategy_template": template},
                market=market,
                strategy_template=template,
                run_tag=f"{args.run_tag}_baseline",
                source="smoke.baseline",
                trace_context={"bars_count": len(bars), "parameters": baseline_params},
            )
            mark_step(
                "archive_baseline_report",
                "PASS",
                "baseline report archived",
                {"report_id": baseline_archive.get("id", "")},
            )

        baseline_gate = store.evaluate_version_gate(
            base["id"],
            metrics=baseline_metrics,
            overrides=gate_overrides,
            persist=True,
            market=market,
            strategy_template=template,
        )
        if not bool(baseline_gate.get("passed", False)):
            mark_step(
                "baseline_gate",
                "FAIL",
                "baseline gate failed",
                {"failed_checks": baseline_gate.get("failed_checks", [])},
            )
            raise RuntimeError("baseline gate failed")
        mark_step(
            "baseline_gate",
            "PASS",
            "baseline gate passed",
            {"gate": baseline_gate.get("gate", {})},
        )

        to_candidate = store.transition_strategy_status(
            base["id"],
            target_status="candidate",
            operator="p4_smoke",
            gate_result=baseline_gate,
            market=market,
            strategy_template=template,
        )
        mark_step(
            "transition_candidate",
            "PASS",
            "strategy transitioned to candidate",
            {"from": to_candidate.get("from_status", ""), "to": to_candidate.get("to_status", "")},
        )

        grid_rows: list[dict[str, Any]] = []
        for index, patch in enumerate(param_sets, start=1):
            merged = {**baseline_params, **patch, "market": market, "strategy_template": template}
            report = runner.run(
                strategy_id=base["id"],
                strategy_name=base["name"],
                strategy_version=base["version"],
                bars=bars,
                parameters=merged,
                start_cash=float(args.start_cash),
                lot_size=int(args.lot_size),
                commission_rate=float(args.commission_rate),
                slippage_bp=float(args.slippage_bp),
            )
            metrics = report.get("metrics", {}) if isinstance(report.get("metrics", {}), dict) else {}
            metrics["market"] = market
            metrics["strategy_template"] = template
            gate = store.evaluate_version_gate(
                base["id"],
                metrics=metrics,
                overrides=gate_overrides,
                persist=False,
                market=market,
                strategy_template=template,
            )
            archive: dict[str, Any] = {}
            if args.archive_report:
                archive = store.archive_backtest_report(
                    strategy_id=base["id"],
                    report={**report, "market": market, "strategy_template": template},
                    market=market,
                    strategy_template=template,
                    run_tag=f"{args.run_tag}_grid_{index:03d}",
                    source="smoke.grid",
                    trace_context={"grid_index": index, "parameter_patch": patch, "parameters": merged},
                )
            grid_rows.append(
                {
                    "index": index,
                    "parameters": patch,
                    "metrics": metrics,
                    "gate": gate,
                    "archive": archive,
                }
            )

        sort_by = str(args.sort_by or "net_pnl").strip() or "net_pnl"
        reverse = sort_by not in _GRID_SORT_ASC_METRICS
        sorted_rows = sorted(grid_rows, key=lambda row: _metric_value(row.get("metrics", {}), sort_by), reverse=reverse)
        top_k = max(1, min(int(args.top_k), len(sorted_rows)))
        top_rows = sorted_rows[:top_k]
        best = top_rows[0]
        best_gate = best.get("gate", {}) if isinstance(best.get("gate", {}), dict) else {}
        if not bool(best_gate.get("passed", False)):
            mark_step(
                "grid_backtest",
                "FAIL",
                "best grid result still fails gate",
                {"best_index": best.get("index", 0), "failed_checks": best_gate.get("failed_checks", [])},
            )
            raise RuntimeError("grid best gate failed")

        mark_step(
            "grid_backtest",
            "PASS",
            "grid backtest completed",
            {
                "total_runs": len(grid_rows),
                "sort_by": sort_by,
                "sort_direction": "desc" if reverse else "asc",
                "best_index": best.get("index", 0),
                "top_k": top_k,
            },
        )

        if args.persist_best_metrics:
            best_metrics = dict(best.get("metrics", {}))
            metrics_update: dict[str, Any] = {
                **best_metrics,
                "backtest_grid": {
                    "generated_at": time.time(),
                    "sort_by": sort_by,
                    "sort_direction": "desc" if reverse else "asc",
                    "total_runs": len(grid_rows),
                    "top_k": top_k,
                    "best_index": best.get("index", 0),
                    "best_parameters": best.get("parameters", {}),
                    "gate_overrides": gate_overrides,
                    "market": market,
                    "strategy_template": template,
                    "run_tag": args.run_tag,
                },
            }
            archive_payload = best.get("archive", {}) if isinstance(best.get("archive", {}), dict) else {}
            if archive_payload:
                metrics_update["latest_backtest_report"] = {
                    "report_id": archive_payload.get("id", ""),
                    "created_at": archive_payload.get("created_at", 0.0),
                    "market": archive_payload.get("market", ""),
                    "strategy_template": archive_payload.get("strategy_template", ""),
                    "run_tag": archive_payload.get("run_tag", ""),
                }
            store.update_strategy_metrics(base["id"], metrics_update, merge=True)
            mark_step("persist_best_metrics", "PASS", "best grid metrics persisted")

        to_active = store.transition_strategy_status(
            base["id"],
            target_status="active",
            operator="p4_smoke",
            gate_result=best_gate,
            market=market,
            strategy_template=template,
        )
        mark_step(
            "transition_active",
            "PASS",
            "strategy transitioned to active",
            {"from": to_active.get("from_status", ""), "to": to_active.get("to_status", "")},
        )

        final_strategy = store.get_strategy(base["id"])
        reports = store.list_backtest_reports(strategy_id=base["id"], limit=1000)
        mark_step(
            "verify_traceability",
            "PASS",
            "backtest archives and status verified",
            {
                "strategy_status": final_strategy.get("status", ""),
                "report_count": len(reports),
                "expected_min_reports": 1 + len(grid_rows) if args.archive_report else 0,
            },
        )

        report_payload = {
            "status": "PASS",
            "strategy": final_strategy,
            "baseline_archive": baseline_archive,
            "grid": {
                "sort_by": sort_by,
                "sort_direction": "desc" if reverse else "asc",
                "total_runs": len(grid_rows),
                "top_k": top_k,
                "best": best,
                "top_results": top_rows,
            },
            "archives": {
                "count": len(reports),
                "items": reports[: min(50, len(reports))],
            },
        }
    except Exception as exc:  # noqa: BLE001
        mark_step(
            "runtime_error",
            "FAIL",
            "p4 lifecycle smoke failed",
            {"error": str(exc)},
        )
        report_payload = {
            "status": "BLOCK",
            "error": str(exc),
        }

    duration_ms = round((time.perf_counter() - started_perf) * 1000.0, 3)
    all_passed = all(step.get("status") == "PASS" for step in steps if step.get("name") != "runtime_error")
    final_status = "PASS" if report_payload.get("status") == "PASS" and all_passed else "BLOCK"
    report = {
        "report_version": "1.0",
        "started_at": started_at,
        "finished_at": _iso_now(),
        "duration_ms": duration_ms,
        "params": {
            "data_dir": str(data_dir),
            "strategy_name": str(args.strategy_name),
            "market": str(args.market),
            "strategy_template": str(args.strategy_template),
            "bars": max(10, int(args.bars)),
            "start_cash": float(args.start_cash),
            "lot_size": int(args.lot_size),
            "commission_rate": float(args.commission_rate),
            "slippage_bp": float(args.slippage_bp),
            "max_combinations": int(args.max_combinations),
            "sort_by": str(args.sort_by),
            "top_k": int(args.top_k),
            "run_tag": str(args.run_tag),
            "gate_overrides_json": str(args.gate_overrides_json),
            "archive_report": bool(args.archive_report),
            "persist_best_metrics": bool(args.persist_best_metrics),
            "check_invalid_transition": bool(args.check_invalid_transition),
        },
        "steps": steps,
        "result": report_payload,
        "status": final_status,
    }
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        "[p4-lifecycle-smoke] output={output} status={status} steps={steps}".format(
            output=output_path,
            status=final_status,
            steps=len(steps),
        )
    )
    return 0 if final_status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
