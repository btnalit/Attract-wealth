from __future__ import annotations

import difflib
import hashlib
import itertools
import json
import logging
import time
from typing import Any
from urllib.parse import quote_plus

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from src.core.schemas import BaseSchema

from src.core.errors import TradingServiceError, error_response, ok_response
from src.services.strategy_service import StrategyService

router = APIRouter()
logger = logging.getLogger(__name__)

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


class KnowledgeIngestRequest(BaseModel):
    type: str = Field(default="rule", description="pattern/lesson/rule")
    title: str = Field(default="", description="条目标题")
    content: str = Field(default="", description="条目正文")
    tags: list[str] = Field(default_factory=list, description="标签列表")
    priority: int = Field(default=0, ge=0, le=100, description="规则优先级（rule 类型生效）")
    context: dict[str, Any] = Field(default_factory=dict, description="上下文字段（pattern 类型）")


class KnowledgeDeleteRequest(BaseModel):
    id: str = Field(..., description="知识条目 ID")


class MemoryTierActionRequest(BaseModel):
    id: str = Field(..., description="记忆条目 ID")
    current_tier: str = Field(default="WARM", description="当前层级 HOT/WARM/COLD")


class MemoryForgetRequest(BaseModel):
    id: str = Field(..., description="记忆条目 ID")


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


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _pick_metric(metrics: dict[str, Any], *aliases: str) -> float:
    for alias in aliases:
        if alias in metrics:
            return _to_float(metrics.get(alias), 0.0)
    return 0.0


def _build_parameter_diff(current_params: dict[str, Any], baseline_params: dict[str, Any]) -> dict[str, list[str]]:
    current_keys = set(current_params.keys())
    baseline_keys = set(baseline_params.keys())
    added = sorted(list(current_keys - baseline_keys))
    removed = sorted(list(baseline_keys - current_keys))
    changed = sorted(
        [key for key in (current_keys & baseline_keys) if current_params.get(key) != baseline_params.get(key)]
    )
    return {"added": added, "removed": removed, "changed": changed}


def _format_diff_value(value: Any, *, limit: int = 120) -> str:
    """将 diff 值格式化为可展示文本。"""
    if value is None:
        text = "null"
    elif isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    else:
        text = str(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _try_parse_json_object(raw_content: str) -> dict[str, Any] | None:
    text = str(raw_content or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except Exception:  # noqa: BLE001
        return None
    return payload if isinstance(payload, dict) else None


def _build_content_diff(current_content: str, baseline_content: str) -> dict[str, Any]:
    """构建字段级内容差异（优先 JSON 字段 diff，降级为文本行块 diff）。"""
    current_text = str(current_content or "")
    baseline_text = str(baseline_content or "")
    current_obj = _try_parse_json_object(current_text)
    baseline_obj = _try_parse_json_object(baseline_text)

    if current_obj is not None and baseline_obj is not None:
        current_keys = set(current_obj.keys())
        baseline_keys = set(baseline_obj.keys())
        all_keys = sorted(list(current_keys | baseline_keys))

        added_count = 0
        removed_count = 0
        changed_count = 0
        fields: list[dict[str, Any]] = []
        for key in all_keys:
            has_current = key in current_obj
            has_baseline = key in baseline_obj
            if has_current and not has_baseline:
                status = "added"
                added_count += 1
            elif has_baseline and not has_current:
                status = "removed"
                removed_count += 1
            elif current_obj.get(key) != baseline_obj.get(key):
                status = "changed"
                changed_count += 1
            else:
                continue

            fields.append(
                {
                    "field": key,
                    "status": status,
                    "current_value": _format_diff_value(current_obj.get(key)),
                    "baseline_value": _format_diff_value(baseline_obj.get(key)),
                }
            )

        return {
            "mode": "json_fields",
            "changed": bool(fields),
            "summary": {
                "added_fields": added_count,
                "removed_fields": removed_count,
                "changed_fields": changed_count,
                "total_changed_fields": len(fields),
            },
            "fields": fields[:120],
            "truncated": len(fields) > 120,
        }

    baseline_lines = baseline_text.splitlines()
    current_lines = current_text.splitlines()
    matcher = difflib.SequenceMatcher(None, baseline_lines, current_lines)

    added_line_count = 0
    removed_line_count = 0
    changed_line_count = 0
    changes: list[dict[str, Any]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "insert":
            added_line_count += max(0, j2 - j1)
        elif tag == "delete":
            removed_line_count += max(0, i2 - i1)
        else:
            changed_line_count += max(0, max(i2 - i1, j2 - j1))
        changes.append(
            {
                "type": tag,
                "baseline_range": [i1 + 1, i2],
                "current_range": [j1 + 1, j2],
                "baseline_lines": baseline_lines[i1:i2][:12],
                "current_lines": current_lines[j1:j2][:12],
            }
        )

    return {
        "mode": "text_lines",
        "changed": bool(changes) or current_text != baseline_text,
        "summary": {
            "baseline_line_count": len(baseline_lines),
            "current_line_count": len(current_lines),
            "change_blocks": len(changes),
            "added_lines": added_line_count,
            "removed_lines": removed_line_count,
            "changed_lines": changed_line_count,
        },
        "changes": changes[:80],
        "truncated": len(changes) > 80,
    }


def _get_latest_report(strategy_service: StrategyService, strategy_id: str) -> dict[str, Any] | None:
    if not str(strategy_id or "").strip():
        return None
    rows = strategy_service.list_backtest_reports(strategy_id=str(strategy_id).strip(), limit=1)
    if not rows:
        return None
    item = rows[0]
    return item if isinstance(item, dict) else None


def _normalize_knowledge_type(raw: str) -> str:
    value = str(raw or "").strip().lower()
    mapping = {
        "pattern": "pattern",
        "patterns": "pattern",
        "lesson": "lesson",
        "lessons": "lesson",
        "rule": "rule",
        "rules": "rule",
        "all": "all",
    }
    return mapping.get(value, "all")


def _normalize_memory_tier(raw: str) -> str | None:
    value = str(raw or "").strip().upper()
    if value in {"HOT", "WARM", "COLD"}:
        return value
    return None


def _normalize_knowledge_tags(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed if str(item).strip()]
            except Exception:  # noqa: BLE001
                pass
        return [item.strip() for item in text.split(",") if item.strip()]
    return []


def _normalize_knowledge_vector(raw: Any) -> list[float] | None:
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        try:
            x = float(raw[0])
            y = float(raw[1])
            if 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0:
                return [round(x * 2 - 1, 6), round(y * 2 - 1, 6)]
            return [round(max(-1.0, min(1.0, x)), 6), round(max(-1.0, min(1.0, y)), 6)]
        except (TypeError, ValueError):
            pass
    return None


def _resolve_memory_tier(relevance: float) -> str:
    score = max(0.0, min(100.0, float(relevance)))
    if score >= 80.0:
        return "HOT"
    if score >= 55.0:
        return "WARM"
    return "COLD"


def _normalize_knowledge_entry(raw: dict[str, Any], *, default_type: str) -> dict[str, Any]:
    type_value = str(raw.get("entry_type") or default_type or "rule").strip().lower()
    if type_value in {"patterns", "pattern"}:
        item_type = "Pattern"
    elif type_value in {"lessons", "lesson"}:
        item_type = "Lesson"
    else:
        item_type = "Rule"

    entry_id = str(raw.get("id") or raw.get("vector_id") or f"kb_{hashlib.md5(str(raw).encode('utf-8')).hexdigest()[:12]}")
    title = (
        str(raw.get("title", "")).strip()
        or str(raw.get("name", "")).strip()
        or str(raw.get("rule_text", "")).strip()
        or f"{item_type} {entry_id[:8]}"
    )
    full_content = (
        str(raw.get("content", "")).strip()
        or str(raw.get("description", "")).strip()
        or str(raw.get("rule_text", "")).strip()
    )
    summary = full_content if len(full_content) <= 160 else f"{full_content[:157]}..."
    tags = _normalize_knowledge_tags(raw.get("tags", []))

    relevance_raw = _to_float(raw.get("relevance_score", raw.get("score", 0.0)), default=0.0)
    if relevance_raw <= 1.0:
        relevance = relevance_raw * 100.0
    else:
        relevance = relevance_raw
    relevance = round(max(0.0, min(100.0, relevance)), 2)
    memory_tier = _resolve_memory_tier(relevance)

    vector = _normalize_knowledge_vector(raw.get("vector"))

    return {
        "id": entry_id,
        "title": title,
        "type": item_type,
        "relevance": relevance,
        "memory_tier": memory_tier,
        "summary": summary,
        "tags": tags,
        "fullContent": full_content,
        "vector": vector,
    }


def _flatten_knowledge_results(raw: Any, *, requested_type: str, top_k: int) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    group_map = {"pattern": "patterns", "lesson": "lessons", "rule": "rules"}

    if isinstance(raw, dict):
        if requested_type == "all":
            for source_key in ("patterns", "lessons", "rules"):
                values = raw.get(source_key, [])
                if not isinstance(values, list):
                    continue
                source_type = source_key[:-1] if source_key.endswith("s") else source_key
                for item in values:
                    if isinstance(item, dict):
                        records.append(_normalize_knowledge_entry(item, default_type=source_type))
        else:
            values = raw.get(group_map.get(requested_type, "patterns"), [])
            if isinstance(values, list):
                for item in values:
                    if isinstance(item, dict):
                        records.append(_normalize_knowledge_entry(item, default_type=requested_type))
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                records.append(_normalize_knowledge_entry(item, default_type=requested_type))

    records.sort(key=lambda item: float(item.get("relevance", 0.0)), reverse=True)
    return records[:top_k]


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


def _get_strategy_service(request: Request) -> StrategyService:
    strategy_service = getattr(request.app.state, "strategy_service", None)
    if not isinstance(strategy_service, StrategyService):
        strategy_service = StrategyService(
            strategy_store=getattr(request.app.state, "strategy_store", None),
            backtest_runner=getattr(request.app.state, "backtest_runner", None),
            memory_vault_dao=getattr(request.app.state, "memory_vault_dao", None),
        )
        request.app.state.strategy_service = strategy_service
    else:
        strategy_service.sync_dependencies(
            strategy_store=getattr(request.app.state, "strategy_store", None),
            backtest_runner=getattr(request.app.state, "backtest_runner", None),
            memory_vault_dao=getattr(request.app.state, "memory_vault_dao", None),
        )
    return strategy_service


@router.post("/versions")
async def create_strategy_version(req: StrategyCreateRequest, request: Request):
    try:
        strategy_service = _get_strategy_service(request)
        payload = strategy_service.create_strategy_version(
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
        strategy_service = _get_strategy_service(request)
        rows = strategy_service.list_strategy_versions(name=name, status=status, limit=limit)
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
        strategy_service = _get_strategy_service(request)
        payload = strategy_service.get_strategy(strategy_id)
        return ok_response(payload, code="STRATEGY_VERSION_OK")
    except TradingServiceError as exc:
        return _error_json(exc)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=error_response("INTERNAL_ERROR", "查询策略版本详情失败", {"error": str(exc)}),
        )


@router.get("/versions/{strategy_id}/diff")
async def get_strategy_version_diff(
    strategy_id: str,
    request: Request,
    baseline_id: str = Query(default=""),
):
    """比较策略版本差异，默认基线为父版本或同名上一版本。"""
    try:
        strategy_service = _get_strategy_service(request)
        current = strategy_service.get_strategy(strategy_id)

        baseline: dict[str, Any] | None = None
        baseline_source = "none"
        explicit_baseline_id = str(baseline_id or "").strip()
        if explicit_baseline_id:
            baseline = strategy_service.get_strategy(explicit_baseline_id)
            baseline_source = "explicit"
        else:
            parent_id = str(current.get("parent_id", "")).strip()
            if parent_id:
                try:
                    baseline = strategy_service.get_strategy(parent_id)
                    baseline_source = "parent"
                except TradingServiceError as exc:
                    if exc.code != "STRATEGY_NOT_FOUND":
                        raise

            if baseline is None:
                current_name = str(current.get("name", "")).strip()
                current_version = _to_int(current.get("version", 0), 0)
                siblings = strategy_service.list_strategy_versions(name=current_name, limit=200)
                candidates = [
                    item
                    for item in siblings
                    if str(item.get("id", "")) != str(current.get("id", ""))
                    and _to_int(item.get("version", 0), 0) < current_version
                ]
                if candidates:
                    baseline = sorted(
                        candidates,
                        key=lambda item: _to_int(item.get("version", 0), 0),
                        reverse=True,
                    )[0]
                    baseline_source = "previous_version"

        current_metrics = current.get("metrics", {}) if isinstance(current.get("metrics"), dict) else {}
        baseline_metrics = baseline.get("metrics", {}) if isinstance((baseline or {}).get("metrics"), dict) else {}

        metric_diff = {
            "trade_count": {
                "current": _to_int(_pick_metric(current_metrics, "trade_count", "trades"), 0),
                "baseline": _to_int(_pick_metric(baseline_metrics, "trade_count", "trades"), 0),
            },
            "win_rate": {
                "current": _pick_metric(current_metrics, "win_rate"),
                "baseline": _pick_metric(baseline_metrics, "win_rate"),
            },
            "sharpe": {
                "current": _pick_metric(current_metrics, "sharpe", "sharpe_ratio"),
                "baseline": _pick_metric(baseline_metrics, "sharpe", "sharpe_ratio"),
            },
            "max_drawdown": {
                "current": _pick_metric(current_metrics, "max_drawdown"),
                "baseline": _pick_metric(baseline_metrics, "max_drawdown"),
            },
            "net_pnl": {
                "current": _pick_metric(current_metrics, "net_pnl", "total_pnl"),
                "baseline": _pick_metric(baseline_metrics, "net_pnl", "total_pnl"),
            },
        }
        for item in metric_diff.values():
            item["delta"] = round(_to_float(item.get("current", 0.0)) - _to_float(item.get("baseline", 0.0)), 6)

        current_params = current.get("parameters", {}) if isinstance(current.get("parameters"), dict) else {}
        baseline_params = baseline.get("parameters", {}) if isinstance((baseline or {}).get("parameters"), dict) else {}
        parameter_diff = _build_parameter_diff(current_params, baseline_params)
        current_content = str(current.get("content", "") or "")
        baseline_content = str((baseline or {}).get("content", "") or "")
        content_diff = _build_content_diff(current_content=current_content, baseline_content=baseline_content)

        current_report = _get_latest_report(strategy_service, str(current.get("id", "")))
        baseline_report = _get_latest_report(strategy_service, str((baseline or {}).get("id", ""))) if baseline else None
        current_report_id = str((current_report or {}).get("id", ""))
        baseline_report_id = str((baseline_report or {}).get("id", ""))
        compare_ready = bool(current_report_id and baseline_report_id)
        compare_page_url = (
            f"/backtest?compareA={quote_plus(current_report_id)}&compareB={quote_plus(baseline_report_id)}"
            if compare_ready
            else ""
        )

        payload = {
            "strategy_id": str(current.get("id", "")),
            "baseline_id": str((baseline or {}).get("id", "")),
            "baseline_source": baseline_source,
            "has_baseline": baseline is not None,
            "current": {
                "id": str(current.get("id", "")),
                "name": str(current.get("name", "")),
                "version": _to_int(current.get("version", 0), 0),
                "status": str(current.get("status", "")),
            },
            "baseline": (
                {
                    "id": str(baseline.get("id", "")),
                    "name": str(baseline.get("name", "")),
                    "version": _to_int(baseline.get("version", 0), 0),
                    "status": str(baseline.get("status", "")),
                }
                if baseline
                else None
            ),
            "metric_diff": metric_diff,
            "parameter_diff": parameter_diff,
            "content_changed": bool(content_diff.get("changed", False)),
            "content_diff": content_diff,
            "backtest_compare": {
                "current_report_id": current_report_id,
                "baseline_report_id": baseline_report_id,
                "current_report_created_at": _to_float((current_report or {}).get("created_at", 0.0), 0.0),
                "baseline_report_created_at": _to_float((baseline_report or {}).get("created_at", 0.0), 0.0),
                "compare_ready": compare_ready,
                "compare_page_url": compare_page_url,
                "current_report_url": f"/api/strategy/backtests/{current_report_id}" if current_report_id else "",
                "baseline_report_url": f"/api/strategy/backtests/{baseline_report_id}" if baseline_report_id else "",
            },
        }
        return ok_response(payload, code="STRATEGY_VERSION_DIFF_OK")
    except TradingServiceError as exc:
        return _error_json(exc)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=error_response("INTERNAL_ERROR", "策略版本差异计算失败", {"error": str(exc)}),
        )


@router.post("/backtest")
async def run_strategy_backtest(req: StrategyBacktestRequest, request: Request):
    try:
        strategy_service = _get_strategy_service(request)
        strategy = strategy_service.get_strategy(req.strategy_id)
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
        report = strategy_service.run_backtest(
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
            archive_record = strategy_service.archive_backtest_report(
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
            strategy_service.update_strategy_metrics(strategy["id"], metrics_update, merge=True)
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
        strategy_service = _get_strategy_service(request)
        strategy = strategy_service.get_strategy(req.strategy_id)
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
            report = strategy_service.run_backtest(
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
                gate_eval = strategy_service.evaluate_version_gate(
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
                archive = strategy_service.archive_backtest_report(
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
            strategy_service.update_strategy_metrics(strategy["id"], metrics_update, merge=True)

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
        strategy_service = _get_strategy_service(request)
        payload = strategy_service.evaluate_version_gate(
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
        strategy_service = _get_strategy_service(request)
        payload = strategy_service.transition_strategy_status(
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
        strategy_service = _get_strategy_service(request)
        rows = strategy_service.list_backtest_reports(
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
        strategy_service = _get_strategy_service(request)
        payload = strategy_service.get_backtest_report(report_id)
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
        strategy_service = _get_strategy_service(request)
        gate_result = None
        if req.run_gate and not req.force:
            gate_result = strategy_service.evaluate_version_gate(
                strategy_id,
                overrides=_collect_gate_overrides(req),
                persist=True,
                market=req.market,
                strategy_template=req.strategy_template,
            )
        payload = strategy_service.promote_strategy_version(
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
    top_k: int = Query(10, ge=1, le=100),
):
    """Search knowledge base and return frontend-friendly normalized entries."""
    strategy_service = _get_strategy_service(request)
    knowledge_type = _normalize_knowledge_type(type)
    query_text = str(q or "").strip()
    try:
        raw_results = strategy_service.search_knowledge(
            knowledge_type=knowledge_type,
            query_text=query_text,
            top_k=top_k,
        )
    except ImportError as exc:
        logger.warning("KnowledgeCore import failed, return empty knowledge list: %s", exc)
        return ok_response([], code="KNOWLEDGE_CORE_UNAVAILABLE")
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=error_response("INTERNAL_ERROR", "Knowledge core init failed", {"error": str(exc)}),
        )

    payload = _flatten_knowledge_results(raw_results, requested_type=knowledge_type, top_k=top_k)
    return ok_response(payload, code="KNOWLEDGE_SEARCH_OK")


@router.post("/knowledge/ingest")
async def ingest_knowledge(req: KnowledgeIngestRequest, request: Request):
    """摄入一条知识到知识库。"""
    strategy_service = _get_strategy_service(request)
    knowledge_type = _normalize_knowledge_type(req.type)
    if knowledge_type == "all":
        return JSONResponse(
            status_code=400,
            content=error_response(
                "INVALID_STRATEGY_REQUEST",
                "知识类型不合法",
                {"type": req.type, "allowed": ["pattern", "lesson", "rule"]},
            ),
        )

    title = str(req.title or "").strip()
    content = str(req.content or "").strip()
    if not content:
        return JSONResponse(
            status_code=400,
            content=error_response("INVALID_STRATEGY_REQUEST", "content 不能为空", {"field": "content"}),
        )
    if knowledge_type in {"pattern", "lesson"} and not title:
        return JSONResponse(
            status_code=400,
            content=error_response("INVALID_STRATEGY_REQUEST", "title 不能为空", {"field": "title"}),
        )

    try:
        payload = strategy_service.ingest_knowledge(
            knowledge_type=knowledge_type,
            title=title,
            content=content,
            tags=_normalize_knowledge_tags(req.tags),
            priority=int(req.priority),
            context=dict(req.context or {}),
        )
        return ok_response(payload, code="KNOWLEDGE_INGEST_OK")
    except ImportError as exc:
        logger.warning("KnowledgeCore import failed for ingest: %s", exc)
        return JSONResponse(
            status_code=503,
            content=error_response("KNOWLEDGE_CORE_UNAVAILABLE", "Knowledge core not available", {"error": str(exc)}),
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=error_response("INTERNAL_ERROR", "Knowledge ingest failed", {"error": str(exc)}),
        )


@router.post("/knowledge/delete")
async def delete_knowledge(req: KnowledgeDeleteRequest, request: Request):
    """删除一条知识条目。"""
    strategy_service = _get_strategy_service(request)
    entry_id = str(req.id or "").strip()
    if not entry_id:
        return JSONResponse(
            status_code=400,
            content=error_response("INVALID_STRATEGY_REQUEST", "id 不能为空", {"field": "id"}),
        )

    try:
        deleted = strategy_service.delete_knowledge(entry_id=entry_id)
        if not deleted:
            return JSONResponse(
                status_code=404,
                content=error_response("KNOWLEDGE_NOT_FOUND", "知识条目不存在", {"id": entry_id}),
            )
        return ok_response({"id": entry_id, "deleted": True}, code="KNOWLEDGE_DELETE_OK")
    except ImportError as exc:
        logger.warning("KnowledgeCore import failed for delete: %s", exc)
        return JSONResponse(
            status_code=503,
            content=error_response("KNOWLEDGE_CORE_UNAVAILABLE", "Knowledge core not available", {"error": str(exc)}),
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=error_response("INTERNAL_ERROR", "Knowledge delete failed", {"error": str(exc)}),
        )


# ---------------------------------------------------------------------------
# Memory Vault API (Phase 5 QA Rework — T-MV-01)
# ---------------------------------------------------------------------------

@router.get("/memory/overrides")
async def get_memory_overrides(request: Request):
    """查询 MemoryVault 的层级覆盖与遗忘状态。"""
    strategy_service = _get_strategy_service(request)
    try:
        payload = strategy_service.get_memory_overrides()
        return ok_response(payload, code="MEMORY_OVERRIDES_OK")
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=error_response("INTERNAL_ERROR", "Memory overrides query failed", {"error": str(exc)}),
        )


@router.post("/memory/promote")
async def promote_memory(req: MemoryTierActionRequest, request: Request):
    """提升记忆层级（COLD->WARM->HOT）。"""
    strategy_service = _get_strategy_service(request)
    entry_id = str(req.id or "").strip()
    if not entry_id:
        return JSONResponse(
            status_code=400,
            content=error_response("INVALID_STRATEGY_REQUEST", "id 不能为空", {"field": "id"}),
        )
    current_tier = _normalize_memory_tier(req.current_tier)
    if not current_tier:
        return JSONResponse(
            status_code=400,
            content=error_response(
                "INVALID_STRATEGY_REQUEST",
                "current_tier 不合法",
                {"field": "current_tier", "allowed": ["HOT", "WARM", "COLD"]},
            ),
        )
    try:
        payload = strategy_service.promote_memory(entry_id=entry_id, current_tier=current_tier)
        return ok_response(payload, code="MEMORY_PROMOTE_OK")
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content=error_response("INVALID_STRATEGY_REQUEST", "记忆提升参数不合法", {"error": str(exc)}),
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=error_response("INTERNAL_ERROR", "Memory promote failed", {"error": str(exc)}),
        )


@router.post("/memory/demote")
async def demote_memory(req: MemoryTierActionRequest, request: Request):
    """降低记忆层级（HOT->WARM->COLD）。"""
    strategy_service = _get_strategy_service(request)
    entry_id = str(req.id or "").strip()
    if not entry_id:
        return JSONResponse(
            status_code=400,
            content=error_response("INVALID_STRATEGY_REQUEST", "id 不能为空", {"field": "id"}),
        )
    current_tier = _normalize_memory_tier(req.current_tier)
    if not current_tier:
        return JSONResponse(
            status_code=400,
            content=error_response(
                "INVALID_STRATEGY_REQUEST",
                "current_tier 不合法",
                {"field": "current_tier", "allowed": ["HOT", "WARM", "COLD"]},
            ),
        )
    try:
        payload = strategy_service.demote_memory(entry_id=entry_id, current_tier=current_tier)
        return ok_response(payload, code="MEMORY_DEMOTE_OK")
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content=error_response("INVALID_STRATEGY_REQUEST", "记忆降级参数不合法", {"error": str(exc)}),
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=error_response("INTERNAL_ERROR", "Memory demote failed", {"error": str(exc)}),
        )


@router.post("/memory/forget")
async def forget_memory(req: MemoryForgetRequest, request: Request):
    """遗忘记忆条目（仅标记隐藏，不删除知识主数据）。"""
    strategy_service = _get_strategy_service(request)
    entry_id = str(req.id or "").strip()
    if not entry_id:
        return JSONResponse(
            status_code=400,
            content=error_response("INVALID_STRATEGY_REQUEST", "id 不能为空", {"field": "id"}),
        )
    try:
        payload = strategy_service.forget_memory(entry_id=entry_id)
        return ok_response(payload, code="MEMORY_FORGET_OK")
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content=error_response("INVALID_STRATEGY_REQUEST", "记忆遗忘参数不合法", {"error": str(exc)}),
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=error_response("INTERNAL_ERROR", "Memory forget failed", {"error": str(exc)}),
        )


# ---------------------------------------------------------------------------
# Strategy History API (Evolution Center — frontend /api/strategy/history)
# ---------------------------------------------------------------------------

@router.get("/history")
async def list_strategy_history(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
):
    """返回策略演化事件历史，供 EvolutionCenter 前端消费。"""
    strategy_service = _get_strategy_service(request)
    try:
        events = strategy_service.list_strategy_history(limit=limit)
        return ok_response(events)
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content=error_response("INTERNAL_ERROR", "Failed to load strategy history", {"error": str(exc)}),
        )

