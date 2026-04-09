from __future__ import annotations

import hashlib
import itertools
import json
import time
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from src.core.schemas import BaseSchema

from src.core.errors import TradingServiceError, error_response, ok_response
from src.core.strategy_store import StrategyStore
from src.evolution.backtest_runner import BacktestRunner

router = APIRouter()

_GRID_SORT_ASC_METRICS = {"max_drawdown"}


class StrategyCreateRequest(BaseModel):
    name: str = Field(..., description="策略名称")
    content: str = Field(default="", description="策略内容")
    origin: str = Field(default="BUILT_IN", description="策略来源")
    parent_id: str = Field(default="", description="父版本 ID")
    parameters: dict[str, Any] = Field(default_factory=dict, description="策略参数")
    metrics: dict[str, Any] = Field(default_factory=dict, description="初始指标")
    status: str = Field(default="draft", description="draft/candidate/active/retired/rejected")
    market: str = Field(default="CN", description="市场，如 CN/US/HK")
    strategy_template: str = Field(default="default", description="策略模板名称")


class BacktestBar(BaseModel):
    ts: str = Field(default="", description="时间戳")
    close: float = Field(..., gt=0, description="收盘价")
    signal: str = Field(default="AUTO", description="BUY/SELL/HOLD/AUTO")


class StrategyBacktestRequest(BaseModel):
    strategy_id: str = Field(..., description="策略版本 ID")
    bars: list[BacktestBar] = Field(..., min_length=2, description="回测 K 线")
    start_cash: float = Field(default=1_000_000.0, gt=0, description="初始资金")
    lot_size: int = Field(default=100, ge=1, description="最小交易单位")
    commission_rate: float = Field(default=0.0003, ge=0, description="手续费率")
    slippage_bp: float = Field(default=1.0, ge=0, description="滑点（bp）")
    parameters_override: dict[str, Any] = Field(default_factory=dict, description="回测参数覆盖")
    persist_metrics: bool = Field(default=True, description="是否写回策略 metrics")
    market: str = Field(default="CN", description="回测市场")
    strategy_template: str = Field(default="default", description="回测策略模板")
    run_tag: str = Field(default="", description="回测批次标签")
    archive_report: bool = Field(default=True, description="是否归档回测报告")


class StrategyBacktestGridRequest(BaseModel):
    strategy_id: str = Field(..., description="策略版本 ID")
    bars: list[BacktestBar] = Field(..., min_length=2, description="回测 K 线")
    parameter_grid: dict[str, list[Any]] = Field(default_factory=dict, description="参数网格")
    parameter_sets: list[dict[str, Any]] = Field(default_factory=list, description="显式参数组合")
    max_combinations: int = Field(default=128, ge=1, le=2000, description="最大组合数")
    start_cash: float = Field(default=1_000_000.0, gt=0, description="初始资金")
    lot_size: int = Field(default=100, ge=1, description="最小交易单位")
    commission_rate: float = Field(default=0.0003, ge=0, description="手续费率")
    slippage_bp: float = Field(default=1.0, ge=0, description="滑点（bp）")
    market: str = Field(default="CN", description="回测市场")
    strategy_template: str = Field(default="default", description="回测策略模板")
    run_tag: str = Field(default="", description="网格批次标签")
    archive_report: bool = Field(default=True, description="是否归档每个组合报告")
    evaluate_gate: bool = Field(default=True, description="是否对每个组合做门禁评估")
    gate_overrides: dict[str, Any] = Field(default_factory=dict, description="门禁阈值覆盖")
    sort_by: str = Field(default="net_pnl", description="排序指标，如 net_pnl/max_drawdown/sharpe")
    top_k: int = Field(default=5, ge=1, le=100, description="返回 TopK")
    persist_best_metrics: bool = Field(default=True, description="是否回写最佳组合指标")


class StrategyGateRequest(BaseModel):
    metrics: dict[str, Any] = Field(default_factory=dict, description="可选，覆盖当前策略 metrics")
    persist: bool = Field(default=True, description="是否持久化门禁评估到 metrics.version_gate")
    min_trades: int | None = Field(default=None, ge=1)
    min_win_rate: float | None = Field(default=None, ge=0, le=1)
    max_drawdown: float | None = Field(default=None, ge=0, le=1)
    min_net_pnl: float | None = Field(default=None)
    min_sharpe: float | None = Field(default=None)
    market: str = Field(default="", description="门禁评估市场覆盖")
    strategy_template: str = Field(default="", description="门禁评估模板覆盖")


class StrategyPromoteRequest(BaseModel):
    operator: str = Field(default="api", description="操作人")
    force: bool = Field(default=False, description="是否强制晋升（跳过门禁）")
    run_gate: bool = Field(default=True, description="晋升前是否执行版本门禁")
    gate_overrides: dict[str, Any] = Field(default_factory=dict, description="门禁参数覆盖")
    market: str = Field(default="", description="门禁市场上下文")
    strategy_template: str = Field(default="", description="门禁模板上下文")


class StrategyTransitionRequest(BaseModel):
    target_status: str = Field(..., description="目标状态，如 candidate/active/retired/rejected")
    operator: str = Field(default="api", description="操作人")
    force: bool = Field(default=False, description="是否强制迁移")
    gate_overrides: dict[str, Any] = Field(default_factory=dict, description="门禁参数覆盖")
    market: str = Field(default="", description="门禁市场上下文")
    strategy_template: str = Field(default="", description="门禁模板上下文")


def _error_json(exc: TradingServiceError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.http_status,
        content=error_response(exc.code, exc.message, exc.details),
    )


def _normalize_market(value: Any) -> str:
    market = str(value or "").strip().upper()
    return market or "CN"


def _normalize_template(value: Any) -> str:
    template = str(value or "").strip().lower()
    return template or "default"


def _stable_hash(payload: Any) -> str:
    try:
        normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except Exception:
        normalized = str(payload)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _collect_gate_overrides(
    req: StrategyGateRequest | StrategyPromoteRequest | StrategyTransitionRequest,
) -> dict[str, Any]:
    if isinstance(req, (StrategyPromoteRequest, StrategyTransitionRequest)):
        overrides = dict(req.gate_overrides or {})
        if str(req.market or "").strip():
            overrides["market"] = req.market
        if str(req.strategy_template or "").strip():
            overrides["strategy_template"] = req.strategy_template
        return overrides

    overrides: dict[str, Any] = {}
    if req.min_trades is not None:
        overrides["min_trades"] = req.min_trades
    if req.min_win_rate is not None:
        overrides["min_win_rate"] = req.min_win_rate
    if req.max_drawdown is not None:
        overrides["max_drawdown"] = req.max_drawdown
    if req.min_net_pnl is not None:
        overrides["min_net_pnl"] = req.min_net_pnl
    if req.min_sharpe is not None:
        overrides["min_sharpe"] = req.min_sharpe
    if str(req.market or "").strip():
        overrides["market"] = req.market
    if str(req.strategy_template or "").strip():
        overrides["strategy_template"] = req.strategy_template
    return overrides


def _build_parameter_sets(req: StrategyBacktestGridRequest) -> list[dict[str, Any]]:
    explicit_sets = [dict(item or {}) for item in req.parameter_sets if isinstance(item, dict)]
    if explicit_sets:
        if len(explicit_sets) > req.max_combinations:
            raise ValueError("parameter_sets exceed max_combinations")
        return explicit_sets

    grid = dict(req.parameter_grid or {})
    if not grid:
        return [{}]

    keys: list[str] = []
    values_list: list[list[Any]] = []
    for key, raw_values in grid.items():
        if not isinstance(raw_values, list) or not raw_values:
            raise ValueError(f"parameter_grid[{key}] must be non-empty list")
        keys.append(str(key))
        values_list.append(list(raw_values))

    total = 1
    for values in values_list:
        total *= len(values)
        if total > req.max_combinations:
            raise ValueError("parameter_grid cartesian product exceeds max_combinations")

    combos: list[dict[str, Any]] = []
    for row in itertools.product(*values_list):
        combos.append(dict(zip(keys, row)))
    return combos


def _metric_sort_value(metrics: dict[str, Any], metric: str) -> float:
    return _to_float(metrics.get(metric, 0.0), 0.0)


def _get_strategy_store(request: Request) -> StrategyStore:
    store = getattr(request.app.state, "strategy_store", None)
    required_methods = {
        "create_strategy_version",
        "list_strategy_versions",
        "get_strategy",
        "update_strategy_metrics",
        "evaluate_version_gate",
        "promote_strategy_version",
        "transition_strategy_status",
        "archive_backtest_report",
        "list_backtest_reports",
        "get_backtest_report",
    }
    if store is None or not all(hasattr(store, name) for name in required_methods):
        store = StrategyStore()
        request.app.state.strategy_store = store
    return store


def _get_backtest_runner(request: Request) -> BacktestRunner:
    runner = getattr(request.app.state, "backtest_runner", None)
    if runner is None or not hasattr(runner, "run"):
        runner = BacktestRunner()
        request.app.state.backtest_runner = runner
    return runner


@router.post("/versions")
async def create_strategy_version(req: StrategyCreateRequest, request: Request):
    try:
        store = _get_strategy_store(request)
        payload = store.create_strategy_version(
            name=req.name,
            content=req.content,
            origin=req.origin,
            parent_id=req.parent_id,
            parameters=req.parameters,
            metrics=req.metrics,
            status=req.status,
            market=req.market,
            strategy_template=req.strategy_template,
        )
        return ok_response(payload, code="STRATEGY_VERSION_CREATED")
    except TradingServiceError as exc:
        return _error_json(exc)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=error_response("INTERNAL_ERROR", "创建策略版本失败", {"error": str(exc)}),
        )


@router.get("/versions")
async def list_strategy_versions(
    request: Request,
    name: str = Query(default=""),
    status: str = Query(default=""),
    limit: int = Query(default=50, ge=1, le=500),
):
    try:
        store = _get_strategy_store(request)
        rows = store.list_strategy_versions(name=name, status=status, limit=limit)
        return ok_response({"items": rows, "count": len(rows)}, code="STRATEGY_VERSIONS_OK")
    except TradingServiceError as exc:
        return _error_json(exc)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=error_response("INTERNAL_ERROR", "查询策略版本失败", {"error": str(exc)}),
        )


@router.get("/versions/{strategy_id}")
async def get_strategy_version(strategy_id: str, request: Request):
    try:
        store = _get_strategy_store(request)
        payload = store.get_strategy(strategy_id)
        return ok_response(payload, code="STRATEGY_VERSION_OK")
    except TradingServiceError as exc:
        return _error_json(exc)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=error_response("INTERNAL_ERROR", "查询策略版本详情失败", {"error": str(exc)}),
        )


@router.post("/backtest")
async def run_strategy_backtest(req: StrategyBacktestRequest, request: Request):
    try:
        store = _get_strategy_store(request)
        runner = _get_backtest_runner(request)
        strategy = store.get_strategy(req.strategy_id)
        merged_params = {
            **(strategy.get("parameters", {}) if isinstance(strategy.get("parameters", {}), dict) else {}),
            **(req.parameters_override or {}),
        }
        resolved_market = _normalize_market(req.market or merged_params.get("market", ""))
        resolved_template = _normalize_template(
            req.strategy_template or merged_params.get("strategy_template", "") or merged_params.get("template", "")
        )
        merged_params["market"] = resolved_market
        merged_params["strategy_template"] = resolved_template

        bars = [{"timestamp": item.ts, "close": item.close, "signal": item.signal} for item in req.bars]
        report = runner.run(
            strategy_id=strategy["id"],
            strategy_name=strategy["name"],
            strategy_version=strategy["version"],
            bars=bars,
            parameters=merged_params,
            start_cash=req.start_cash,
            lot_size=req.lot_size,
            commission_rate=req.commission_rate,
            slippage_bp=req.slippage_bp,
        )
        report["market"] = resolved_market
        report["strategy_template"] = resolved_template
        report_metrics = report.get("metrics", {}) if isinstance(report.get("metrics", {}), dict) else {}
        report_metrics["market"] = resolved_market
        report_metrics["strategy_template"] = resolved_template
        report["metrics"] = report_metrics

        archive_record = None
        if req.archive_report:
            archive_record = store.archive_backtest_report(
                strategy_id=strategy["id"],
                report=report,
                market=resolved_market,
                strategy_template=resolved_template,
                run_tag=req.run_tag,
                source="api",
                bars_hash=_stable_hash(bars),
                params_hash=_stable_hash(
                    {
                        "parameters": merged_params,
                        "start_cash": req.start_cash,
                        "lot_size": req.lot_size,
                        "commission_rate": req.commission_rate,
                        "slippage_bp": req.slippage_bp,
                    }
                ),
                trace_context={
                    "bars": bars,
                    "parameters": merged_params,
                    "runtime": {
                        "start_cash": req.start_cash,
                        "lot_size": req.lot_size,
                        "commission_rate": req.commission_rate,
                        "slippage_bp": req.slippage_bp,
                    },
                },
            )

        if req.persist_metrics:
            metrics_update: dict[str, Any] = dict(report.get("metrics", {}))
            if isinstance(archive_record, dict):
                metrics_update["latest_backtest_report"] = {
                    "report_id": archive_record.get("id", ""),
                    "created_at": archive_record.get("created_at", 0.0),
                    "market": archive_record.get("market", ""),
                    "strategy_template": archive_record.get("strategy_template", ""),
                    "run_tag": archive_record.get("run_tag", ""),
                }
            store.update_strategy_metrics(strategy["id"], metrics_update, merge=True)
        return ok_response(
            {
                "strategy": strategy,
                "backtest": report,
                "metrics_persisted": bool(req.persist_metrics),
                "archived": bool(req.archive_report),
                "archive": archive_record or {},
            },
            code="STRATEGY_BACKTEST_OK",
        )
    except TradingServiceError as exc:
        return _error_json(exc)
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content=error_response("INVALID_STRATEGY_REQUEST", "回测参数不合法", {"error": str(exc)}),
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=error_response("INTERNAL_ERROR", "策略回测失败", {"error": str(exc)}),
        )


@router.post("/backtest/grid")
async def run_strategy_backtest_grid(req: StrategyBacktestGridRequest, request: Request):
    try:
        store = _get_strategy_store(request)
        runner = _get_backtest_runner(request)
        strategy = store.get_strategy(req.strategy_id)
        parameter_sets = _build_parameter_sets(req)
        bars = [{"timestamp": item.ts, "close": item.close, "signal": item.signal} for item in req.bars]

        base_params = strategy.get("parameters", {}) if isinstance(strategy.get("parameters", {}), dict) else {}
        resolved_market = _normalize_market(req.market or base_params.get("market", ""))
        resolved_template = _normalize_template(
            req.strategy_template or base_params.get("strategy_template", "") or base_params.get("template", "")
        )

        rows: list[dict[str, Any]] = []
        for index, patch in enumerate(parameter_sets, start=1):
            merged_params = {**base_params, **dict(patch)}
            merged_params["market"] = resolved_market
            merged_params["strategy_template"] = resolved_template
            report = runner.run(
                strategy_id=strategy["id"],
                strategy_name=strategy["name"],
                strategy_version=strategy["version"],
                bars=bars,
                parameters=merged_params,
                start_cash=req.start_cash,
                lot_size=req.lot_size,
                commission_rate=req.commission_rate,
                slippage_bp=req.slippage_bp,
            )
            report["market"] = resolved_market
            report["strategy_template"] = resolved_template
            metrics = report.get("metrics", {}) if isinstance(report.get("metrics", {}), dict) else {}
            metrics["market"] = resolved_market
            metrics["strategy_template"] = resolved_template
            report["metrics"] = metrics

            gate_eval: dict[str, Any] = {}
            if req.evaluate_gate:
                gate_eval = store.evaluate_version_gate(
                    strategy["id"],
                    metrics=metrics,
                    overrides=dict(req.gate_overrides or {}),
                    persist=False,
                    market=resolved_market,
                    strategy_template=resolved_template,
                )

            archive_record: dict[str, Any] = {}
            if req.archive_report:
                suffix = f"{req.run_tag}#{index:03d}" if str(req.run_tag or "").strip() else f"grid#{index:03d}"
                archive = store.archive_backtest_report(
                    strategy_id=strategy["id"],
                    report=report,
                    market=resolved_market,
                    strategy_template=resolved_template,
                    run_tag=suffix,
                    source="api.grid",
                    bars_hash=_stable_hash(bars),
                    params_hash=_stable_hash(
                        {
                            "parameters": merged_params,
                            "start_cash": req.start_cash,
                            "lot_size": req.lot_size,
                            "commission_rate": req.commission_rate,
                            "slippage_bp": req.slippage_bp,
                        }
                    ),
                    trace_context={
                        "bars": bars,
                        "parameters": merged_params,
                        "parameter_patch": patch,
                        "grid_index": index,
                        "runtime": {
                            "start_cash": req.start_cash,
                            "lot_size": req.lot_size,
                            "commission_rate": req.commission_rate,
                            "slippage_bp": req.slippage_bp,
                        },
                    },
                )
                archive_record = dict(archive)

            rows.append(
                {
                    "index": index,
                    "parameters": dict(patch),
                    "metrics": metrics,
                    "summary": report.get("summary", {}),
                    "gate": gate_eval,
                    "archive": archive_record,
                }
            )

        metric = str(req.sort_by or "net_pnl").strip() or "net_pnl"
        reverse = metric not in _GRID_SORT_ASC_METRICS
        sorted_rows = sorted(rows, key=lambda row: _metric_sort_value(row.get("metrics", {}), metric), reverse=reverse)
        top_k_rows = sorted_rows[: min(req.top_k, len(sorted_rows))]
        best = top_k_rows[0] if top_k_rows else {}

        if req.persist_best_metrics and isinstance(best, dict) and best:
            best_metrics = dict(best.get("metrics", {}))
            metrics_update: dict[str, Any] = {
                **best_metrics,
                "backtest_grid": {
                    "generated_at": time.time(),
                    "market": resolved_market,
                    "strategy_template": resolved_template,
                    "run_tag": req.run_tag,
                    "sort_by": metric,
                    "total_runs": len(rows),
                    "top_k": min(req.top_k, len(rows)),
                    "best_index": best.get("index", 0),
                    "best_parameters": best.get("parameters", {}),
                },
            }
            if isinstance(best.get("archive", {}), dict) and best.get("archive", {}):
                metrics_update["latest_backtest_report"] = {
                    "report_id": best["archive"].get("id", ""),
                    "created_at": best["archive"].get("created_at", 0.0),
                    "market": best["archive"].get("market", ""),
                    "strategy_template": best["archive"].get("strategy_template", ""),
                    "run_tag": best["archive"].get("run_tag", ""),
                }
            store.update_strategy_metrics(strategy["id"], metrics_update, merge=True)

        return ok_response(
            {
                "strategy": strategy,
                "summary": {
                    "total_runs": len(rows),
                    "top_k": len(top_k_rows),
                    "sort_by": metric,
                    "sort_direction": "asc" if not reverse else "desc",
                    "market": resolved_market,
                    "strategy_template": resolved_template,
                    "run_tag": req.run_tag,
                    "archive_report": bool(req.archive_report),
                    "evaluate_gate": bool(req.evaluate_gate),
                },
                "best": best or {},
                "top_results": top_k_rows,
                "all_results": sorted_rows,
                "metrics_persisted": bool(req.persist_best_metrics),
            },
            code="STRATEGY_BACKTEST_GRID_OK",
        )
    except TradingServiceError as exc:
        return _error_json(exc)
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content=error_response("INVALID_STRATEGY_REQUEST", "参数网格不合法", {"error": str(exc)}),
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=error_response("INTERNAL_ERROR", "策略参数网格回测失败", {"error": str(exc)}),
        )


@router.post("/versions/{strategy_id}/gate")
async def evaluate_strategy_gate(strategy_id: str, req: StrategyGateRequest, request: Request):
    try:
        store = _get_strategy_store(request)
        payload = store.evaluate_version_gate(
            strategy_id,
            metrics=req.metrics or None,
            overrides=_collect_gate_overrides(req),
            persist=bool(req.persist),
            market=req.market,
            strategy_template=req.strategy_template,
        )
        code = "STRATEGY_GATE_PASSED" if payload.get("passed", False) else "STRATEGY_GATE_FAILED"
        return ok_response(payload, code=code)
    except TradingServiceError as exc:
        return _error_json(exc)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=error_response("INTERNAL_ERROR", "策略版本门禁评估失败", {"error": str(exc)}),
        )


@router.post("/versions/{strategy_id}/transition")
async def transition_strategy_version(strategy_id: str, req: StrategyTransitionRequest, request: Request):
    try:
        store = _get_strategy_store(request)
        payload = store.transition_strategy_status(
            strategy_id,
            target_status=req.target_status,
            operator=req.operator,
            force=bool(req.force),
            gate_result=None,
            gate_overrides=_collect_gate_overrides(req),
            market=req.market,
            strategy_template=req.strategy_template,
        )
        return ok_response(payload, code="STRATEGY_STATUS_TRANSITIONED")
    except TradingServiceError as exc:
        return _error_json(exc)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=error_response("INTERNAL_ERROR", "策略状态迁移失败", {"error": str(exc)}),
        )


@router.get("/backtests")
async def list_backtest_reports(
    request: Request,
    strategy_id: str = Query(default=""),
    strategy_name: str = Query(default=""),
    market: str = Query(default=""),
    strategy_template: str = Query(default=""),
    run_tag: str = Query(default=""),
    limit: int = Query(default=50, ge=1, le=500),
):
    try:
        store = _get_strategy_store(request)
        rows = store.list_backtest_reports(
            strategy_id=strategy_id,
            strategy_name=strategy_name,
            market=market,
            strategy_template=strategy_template,
            run_tag=run_tag,
            limit=limit,
        )
        return ok_response({"items": rows, "count": len(rows)}, code="STRATEGY_BACKTEST_REPORTS_OK")
    except TradingServiceError as exc:
        return _error_json(exc)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=error_response("INTERNAL_ERROR", "查询回测归档失败", {"error": str(exc)}),
        )


@router.get("/backtests/{report_id}")
async def get_backtest_report(report_id: str, request: Request):
    try:
        store = _get_strategy_store(request)
        payload = store.get_backtest_report(report_id)
        return ok_response(payload, code="STRATEGY_BACKTEST_REPORT_OK")
    except TradingServiceError as exc:
        return _error_json(exc)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=error_response("INTERNAL_ERROR", "查询回测归档详情失败", {"error": str(exc)}),
        )


@router.post("/versions/{strategy_id}/promote")
async def promote_strategy_version(strategy_id: str, req: StrategyPromoteRequest, request: Request):
    try:
        store = _get_strategy_store(request)
        gate_result = None
        if req.run_gate and not req.force:
            gate_result = store.evaluate_version_gate(
                strategy_id,
                overrides=_collect_gate_overrides(req),
                persist=True,
                market=req.market,
                strategy_template=req.strategy_template,
            )
        payload = store.promote_strategy_version(
            strategy_id,
            operator=req.operator,
            force=bool(req.force),
            gate_result=gate_result,
            gate_overrides=_collect_gate_overrides(req),
            market=req.market,
            strategy_template=req.strategy_template,
        )
        return ok_response(payload, code="STRATEGY_PROMOTED")
    except TradingServiceError as exc:
        return _error_json(exc)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=error_response("INTERNAL_ERROR", "策略版本晋升失败", {"error": str(exc)}),
        )


# ---------------------------------------------------------------------------
# Knowledge Hub API (Phase 5 QA Rework — T-KB-01)
# ---------------------------------------------------------------------------

@router.get("/knowledge")
async def search_knowledge(
    request: Request,
    type: str = Query("all"),
    q: str = Query(""),
    top_k: int = Query(10),
):
    """Search knowledge base (LanceDB / file-based fallback)."""
    import time
    try:
        # Try to load KnowledgeCore
        from src.evolution.knowledge_core import KnowledgeCore
        kb = KnowledgeCore()
        if type == "patterns":
            results = kb.search_patterns(q, top_k)
        elif type == "lessons":
            results = kb.search_lessons(q, top_k)
        elif type == "rules":
            results = kb.search_rules(q, top_k)
        else:
            results = kb.search_all(q, top_k)
        return ok_response(results)
    except ImportError:
        # Fallback: return mock entries for frontend demo
        logger.info("KnowledgeCore not available, returning mock entries")
        mock_entries = []
        for i in range(min(top_k, 5)):
            mock_entries.append({
                "id": f"kb_{type}_{i}",
                "entry_type": type if type != "all" else ["pattern", "lesson", "rule"][i % 3],
                "title": f"Sample {type} entry #{i+1}",
                "content": f"This is a mock knowledge entry for query '{q}'.",
                "tags": ["mock", "demo"],
                "relevance_score": round(0.9 - i * 0.1, 2),
                "created_at": time.time() - i * 3600,
            })
        return ok_response({"results": mock_entries, "total": len(mock_entries)})
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content=error_response("INTERNAL_ERROR", "Knowledge search failed", {"error": str(exc)}),
        )
