from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from typing import Any, Callable

from src.core.errors import TradingServiceError
from src.core.storage import get_strategy_db
from src.core.trading_ledger import LedgerEntry, TradingLedger

_ALLOWED_STATUSES = {"draft", "candidate", "active", "retired", "rejected"}
_GATE_KEYS = ("min_trades", "min_win_rate", "max_drawdown", "min_net_pnl", "min_sharpe")
_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"candidate", "rejected"},
    "candidate": {"active", "retired", "rejected"},
    "active": {"retired"},
    "retired": set(),
    "rejected": set(),
}


def _to_json(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False)


def _from_json(raw: Any) -> dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except Exception:  # noqa: BLE001
        return {}
    return payload if isinstance(payload, dict) else {}


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


class StrategyStore:
    """Strategy version storage and promotion gate based on strategies.db."""

    def __init__(self, db_factory: Callable[[], Any] | None = None):
        self._db_factory = db_factory or get_strategy_db

    def create_strategy_version(
        self,
        *,
        name: str,
        content: str = "",
        origin: str = "BUILT_IN",
        parent_id: str = "",
        parameters: dict[str, Any] | None = None,
        metrics: dict[str, Any] | None = None,
        status: str = "draft",
        market: str = "",
        strategy_template: str = "",
    ) -> dict[str, Any]:
        strategy_name = str(name or "").strip()
        if not strategy_name:
            raise TradingServiceError(
                code="INVALID_STRATEGY_REQUEST",
                message="strategy name is required",
                http_status=400,
            )

        normalized_status = str(status or "draft").strip().lower()
        if normalized_status not in _ALLOWED_STATUSES:
            raise TradingServiceError(
                code="INVALID_STRATEGY_REQUEST",
                message=f"invalid strategy status: {status}",
                details={"allowed": sorted(list(_ALLOWED_STATUSES))},
                http_status=400,
            )

        normalized_parameters = dict(parameters or {})
        normalized_market = self._normalize_market(
            market or normalized_parameters.get("market", ""),
            default="CN",
        )
        normalized_template = self._normalize_template(
            strategy_template
            or normalized_parameters.get("strategy_template", "")
            or normalized_parameters.get("template", ""),
            default="default",
        )
        if "market" not in normalized_parameters and normalized_market:
            normalized_parameters["market"] = normalized_market
        if "strategy_template" not in normalized_parameters and normalized_template:
            normalized_parameters["strategy_template"] = normalized_template

        strategy_id = str(uuid.uuid4())
        now = time.time()
        with self._db_factory() as db:
            row = db.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM strategies WHERE name = ?",
                (strategy_name,),
            ).fetchone()
            version = int(row[0] or 1)
            db.execute(
                """
                INSERT INTO strategies
                (id, name, version, parent_id, origin, content, parameters, metrics, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    strategy_id,
                    strategy_name,
                    version,
                    str(parent_id or "").strip(),
                    str(origin or "BUILT_IN").strip().upper(),
                    str(content or ""),
                    _to_json(normalized_parameters),
                    _to_json(metrics),
                    normalized_status,
                    now,
                    now,
                ),
            )

        self._record_audit(
            action="STRATEGY_VERSION_CREATED",
            detail=f"strategy={strategy_name} version={version}",
            metadata={
                "strategy_id": strategy_id,
                "name": strategy_name,
                "version": version,
                "origin": str(origin or "BUILT_IN").strip().upper(),
                "status": normalized_status,
                "market": normalized_market,
                "strategy_template": normalized_template,
            },
        )
        return self.get_strategy(strategy_id)

    def list_strategy_versions(self, *, name: str = "", status: str = "", limit: int = 50) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if str(name or "").strip():
            clauses.append("name = ?")
            params.append(str(name).strip())
        if str(status or "").strip():
            clauses.append("status = ?")
            params.append(str(status).strip().lower())
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            "SELECT id, name, version, parent_id, origin, content, parameters, metrics, status, created_at, updated_at "
            f"FROM strategies {where_sql} ORDER BY updated_at DESC, version DESC LIMIT ?"
        )
        params.append(max(1, int(limit)))
        with self._db_factory() as db:
            rows = db.execute(sql, tuple(params)).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_strategy(self, strategy_id: str) -> dict[str, Any]:
        sid = str(strategy_id or "").strip()
        if not sid:
            raise TradingServiceError(
                code="INVALID_STRATEGY_REQUEST",
                message="strategy_id is required",
                http_status=400,
            )
        with self._db_factory() as db:
            row = db.execute(
                """
                SELECT id, name, version, parent_id, origin, content, parameters, metrics, status, created_at, updated_at
                FROM strategies
                WHERE id = ?
                """,
                (sid,),
            ).fetchone()
        if not row:
            raise TradingServiceError(
                code="STRATEGY_NOT_FOUND",
                message="strategy version not found",
                details={"strategy_id": sid},
                http_status=404,
            )
        return self._row_to_dict(row)

    def update_strategy_metrics(
        self,
        strategy_id: str,
        metrics: dict[str, Any],
        *,
        merge: bool = True,
    ) -> dict[str, Any]:
        payload = dict(metrics or {})
        current = self.get_strategy(strategy_id)
        current_metrics = current.get("metrics", {}) if isinstance(current.get("metrics", {}), dict) else {}
        final_metrics = {**current_metrics, **payload} if merge else payload
        now = time.time()
        with self._db_factory() as db:
            db.execute(
                "UPDATE strategies SET metrics = ?, updated_at = ? WHERE id = ?",
                (_to_json(final_metrics), now, str(strategy_id).strip()),
            )
        return self.get_strategy(strategy_id)

    def set_strategy_status(self, strategy_id: str, status: str) -> dict[str, Any]:
        normalized_status = str(status or "").strip().lower()
        if normalized_status not in _ALLOWED_STATUSES:
            raise TradingServiceError(
                code="INVALID_STRATEGY_REQUEST",
                message=f"invalid strategy status: {status}",
                details={"allowed": sorted(list(_ALLOWED_STATUSES))},
                http_status=400,
            )
        self.get_strategy(strategy_id)
        with self._db_factory() as db:
            db.execute(
                "UPDATE strategies SET status = ?, updated_at = ? WHERE id = ?",
                (normalized_status, time.time(), str(strategy_id).strip()),
            )
        return self.get_strategy(strategy_id)

    @staticmethod
    def _normalize_market(value: Any, *, default: str = "CN") -> str:
        market = str(value or "").strip().upper()
        return market or str(default or "CN").strip().upper() or "CN"

    @staticmethod
    def _normalize_template(value: Any, *, default: str = "default") -> str:
        template = str(value or "").strip().lower()
        return template or str(default or "default").strip().lower() or "default"

    @staticmethod
    def _normalize_run_tag(value: Any) -> str:
        tag = str(value or "").strip()
        if len(tag) <= 64:
            return tag
        return tag[:64]

    @staticmethod
    def _hash_payload(payload: Any) -> str:
        try:
            normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        except Exception:
            normalized = str(payload)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    @staticmethod
    def _pick_case_insensitive(mapping: Any, key: str) -> Any:
        if not isinstance(mapping, dict):
            return None
        if key in mapping:
            return mapping[key]
        key_norm = str(key or "").strip().lower()
        for item_key, item_value in mapping.items():
            if str(item_key).strip().lower() == key_norm:
                return item_value
        return None

    @staticmethod
    def _normalize_gate_value(key: str, value: Any, fallback: float) -> float:
        if key == "min_trades":
            return float(max(1, _to_int(value, int(fallback))))
        if key in {"min_win_rate", "max_drawdown"}:
            return max(0.0, min(1.0, _to_float(value, fallback)))
        return _to_float(value, fallback)

    def _build_default_gate(self) -> dict[str, float]:
        return {
            "min_trades": float(max(1, _to_int(os.getenv("STRATEGY_GATE_MIN_TRADES", "20"), 20))),
            "min_win_rate": max(0.0, min(1.0, _to_float(os.getenv("STRATEGY_GATE_MIN_WIN_RATE", "0.52"), 0.52))),
            "max_drawdown": max(0.0, min(1.0, _to_float(os.getenv("STRATEGY_GATE_MAX_DRAWDOWN", "0.2"), 0.2))),
            "min_net_pnl": _to_float(os.getenv("STRATEGY_GATE_MIN_NET_PNL", "0"), 0.0),
            "min_sharpe": _to_float(os.getenv("STRATEGY_GATE_MIN_SHARPE", "0.5"), 0.5),
        }

    @staticmethod
    def _load_gate_policy() -> dict[str, Any]:
        raw = str(os.getenv("STRATEGY_GATE_RULES_JSON", "")).strip()
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _resolve_gate_context(
        self,
        *,
        strategy: dict[str, Any],
        metrics: dict[str, Any],
        overrides: dict[str, Any],
        market: str = "",
        strategy_template: str = "",
    ) -> dict[str, str]:
        parameters = strategy.get("parameters", {}) if isinstance(strategy.get("parameters", {}), dict) else {}
        resolved_market = self._normalize_market(
            market
            or overrides.get("market", "")
            or metrics.get("market", "")
            or parameters.get("market", "")
            or os.getenv("STRATEGY_GATE_DEFAULT_MARKET", "CN"),
            default="CN",
        )
        resolved_template = self._normalize_template(
            strategy_template
            or overrides.get("strategy_template", "")
            or overrides.get("template", "")
            or metrics.get("strategy_template", "")
            or metrics.get("template", "")
            or parameters.get("strategy_template", "")
            or parameters.get("template", "")
            or os.getenv("STRATEGY_GATE_DEFAULT_TEMPLATE", "default"),
            default="default",
        )
        return {
            "market": resolved_market,
            "strategy_template": resolved_template,
        }

    def _resolve_effective_gate(
        self,
        *,
        default_gate: dict[str, float],
        policy: dict[str, Any],
        context: dict[str, str],
        overrides: dict[str, Any],
    ) -> tuple[dict[str, float], list[dict[str, Any]], dict[str, Any]]:
        gate = dict(default_gate)
        sources: list[dict[str, Any]] = [{"source": "env.defaults", "rules": dict(default_gate)}]

        def apply_rules(source_name: str, raw_rules: Any) -> None:
            if not isinstance(raw_rules, dict):
                return
            patch: dict[str, float] = {}
            for key in _GATE_KEYS:
                if key not in raw_rules:
                    continue
                patch[key] = self._normalize_gate_value(key, raw_rules[key], gate[key])
            if not patch:
                return
            gate.update(patch)
            sources.append({"source": source_name, "rules": patch})

        apply_rules("policy.default", policy.get("default", {}))

        market = context["market"]
        template = context["strategy_template"]
        market_rules = self._pick_case_insensitive(policy.get("markets", {}), market)
        apply_rules(f"policy.markets.{market}", market_rules)

        template_rules = self._pick_case_insensitive(policy.get("templates", {}), template)
        apply_rules(f"policy.templates.{template}", template_rules)

        market_template_map = self._pick_case_insensitive(policy.get("market_template", {}), market)
        market_template_rules = self._pick_case_insensitive(market_template_map, template)
        apply_rules(f"policy.market_template.{market}.{template}", market_template_rules)

        pairs_rules = self._pick_case_insensitive(policy.get("market_template_pairs", {}), f"{market}::{template}")
        apply_rules(f"policy.market_template_pairs.{market}::{template}", pairs_rules)

        manual_overrides: dict[str, Any] = {}
        for key in _GATE_KEYS:
            if key not in overrides:
                continue
            normalized = self._normalize_gate_value(key, overrides[key], gate[key])
            gate[key] = normalized
            manual_overrides[key] = int(normalized) if key == "min_trades" else normalized
        if manual_overrides:
            sources.append({"source": "request.overrides", "rules": dict(manual_overrides)})

        gate["min_trades"] = int(max(1, int(gate["min_trades"])))
        return gate, sources, manual_overrides

    @staticmethod
    def _normalize_status(value: str) -> str:
        return str(value or "").strip().lower()

    def _validate_status(self, status: str) -> str:
        normalized_status = self._normalize_status(status)
        if normalized_status not in _ALLOWED_STATUSES:
            raise TradingServiceError(
                code="INVALID_STRATEGY_REQUEST",
                message=f"invalid strategy status: {status}",
                details={"allowed": sorted(list(_ALLOWED_STATUSES))},
                http_status=400,
            )
        return normalized_status

    @staticmethod
    def _assert_transition_allowed(from_status: str, to_status: str) -> None:
        if from_status == to_status:
            return
        allowed = _ALLOWED_TRANSITIONS.get(from_status, set())
        if to_status not in allowed:
            raise TradingServiceError(
                code="STRATEGY_STATUS_TRANSITION_INVALID",
                message="strategy status transition not allowed",
                details={"from_status": from_status, "to_status": to_status, "allowed": sorted(list(allowed))},
                http_status=409,
            )

    def evaluate_version_gate(
        self,
        strategy_id: str,
        *,
        metrics: dict[str, Any] | None = None,
        overrides: dict[str, Any] | None = None,
        persist: bool = True,
        market: str = "",
        strategy_template: str = "",
    ) -> dict[str, Any]:
        strategy = self.get_strategy(strategy_id)
        strategy_metrics = strategy.get("metrics", {}) if isinstance(strategy.get("metrics", {}), dict) else {}
        evaluated_metrics = dict(metrics or strategy_metrics)
        if not evaluated_metrics:
            raise TradingServiceError(
                code="INVALID_STRATEGY_REQUEST",
                message="metrics are required for strategy gate evaluation",
                details={"strategy_id": strategy_id},
                http_status=400,
            )

        gate_context = self._resolve_gate_context(
            strategy=strategy,
            metrics=evaluated_metrics,
            overrides=dict(overrides or {}),
            market=market,
            strategy_template=strategy_template,
        )
        gate, rule_sources, manual_overrides = self._resolve_effective_gate(
            default_gate=self._build_default_gate(),
            policy=self._load_gate_policy(),
            context=gate_context,
            overrides=dict(overrides or {}),
        )

        trades = int(evaluated_metrics.get("trade_count", 0) or 0)
        win_rate = _to_float(evaluated_metrics.get("win_rate", 0.0), 0.0)
        max_drawdown = _to_float(evaluated_metrics.get("max_drawdown", 1.0), 1.0)
        net_pnl = _to_float(evaluated_metrics.get("net_pnl", 0.0), 0.0)
        sharpe = _to_float(evaluated_metrics.get("sharpe", 0.0), 0.0)

        checks = [
            {
                "metric": "trade_count",
                "value": trades,
                "operator": ">=",
                "threshold": gate["min_trades"],
                "passed": trades >= gate["min_trades"],
            },
            {
                "metric": "win_rate",
                "value": round(win_rate, 6),
                "operator": ">=",
                "threshold": gate["min_win_rate"],
                "passed": win_rate >= gate["min_win_rate"],
            },
            {
                "metric": "max_drawdown",
                "value": round(max_drawdown, 6),
                "operator": "<=",
                "threshold": gate["max_drawdown"],
                "passed": max_drawdown <= gate["max_drawdown"],
            },
            {
                "metric": "net_pnl",
                "value": round(net_pnl, 6),
                "operator": ">=",
                "threshold": gate["min_net_pnl"],
                "passed": net_pnl >= gate["min_net_pnl"],
            },
            {
                "metric": "sharpe",
                "value": round(sharpe, 6),
                "operator": ">=",
                "threshold": gate["min_sharpe"],
                "passed": sharpe >= gate["min_sharpe"],
            },
        ]
        passed = all(bool(item["passed"]) for item in checks)
        failed_checks = [item for item in checks if not bool(item["passed"])]
        result = {
            "strategy_id": strategy["id"],
            "strategy_name": strategy["name"],
            "version": strategy["version"],
            "evaluated_at": time.time(),
            "passed": passed,
            "checks": checks,
            "failed_checks": failed_checks,
            "gate": gate,
            "metrics": evaluated_metrics,
            "gate_context": {
                **gate_context,
                "rule_sources": rule_sources,
                "manual_overrides": manual_overrides,
            },
        }
        if persist:
            self.update_strategy_metrics(
                strategy["id"],
                {
                    **evaluated_metrics,
                    "version_gate": {
                        "passed": passed,
                        "evaluated_at": result["evaluated_at"],
                        "checks": checks,
                        "gate": gate,
                        "gate_context": result["gate_context"],
                    },
                },
                merge=True,
            )
        return result

    def transition_strategy_status(
        self,
        strategy_id: str,
        *,
        target_status: str,
        operator: str = "system",
        force: bool = False,
        gate_result: dict[str, Any] | None = None,
        gate_overrides: dict[str, Any] | None = None,
        market: str = "",
        strategy_template: str = "",
    ) -> dict[str, Any]:
        strategy = self.get_strategy(strategy_id)
        from_status = self._normalize_status(strategy.get("status", ""))
        to_status = self._validate_status(target_status)
        if from_status == to_status:
            return {
                "strategy": strategy,
                "from_status": from_status,
                "to_status": to_status,
                "operator": str(operator or "system"),
                "force": bool(force),
                "gate": gate_result or {},
                "demoted_ids": [],
            }

        if not force:
            self._assert_transition_allowed(from_status, to_status)

        evaluation = gate_result
        requires_gate = to_status in {"candidate", "active"}
        if requires_gate and not force:
            if evaluation is None:
                evaluation = self.evaluate_version_gate(
                    strategy["id"],
                    overrides=dict(gate_overrides or {}),
                    persist=True,
                    market=market,
                    strategy_template=strategy_template,
                )
            if not bool(evaluation.get("passed", False)):
                code = "STRATEGY_VERSION_GATE_FAILED" if to_status == "active" else "STRATEGY_CANDIDATE_GATE_FAILED"
                raise TradingServiceError(
                    code=code,
                    message="strategy version gate not passed",
                    details={
                        "strategy_id": strategy["id"],
                        "from_status": from_status,
                        "to_status": to_status,
                        "failed_checks": evaluation.get("failed_checks", []),
                    },
                    http_status=409,
                )

        demoted_ids: list[str] = []
        now = time.time()
        with self._db_factory() as db:
            if to_status == "active":
                rows = db.execute(
                    "SELECT id FROM strategies WHERE name = ? AND status = 'active' AND id != ?",
                    (strategy["name"], strategy["id"]),
                ).fetchall()
                demoted_ids = [str(row[0]) for row in rows]
                if demoted_ids:
                    db.execute(
                        (
                            "UPDATE strategies SET status = 'candidate', updated_at = ? "
                            f"WHERE id IN ({','.join('?' for _ in demoted_ids)})"
                        ),
                        (now, *demoted_ids),
                    )
            db.execute(
                "UPDATE strategies SET status = ?, updated_at = ? WHERE id = ?",
                (to_status, now, strategy["id"]),
            )

        updated = self.get_strategy(strategy["id"])
        self._record_audit(
            action="STRATEGY_STATUS_TRANSITIONED",
            detail=f"strategy={updated['name']} version={updated['version']} {from_status}->{to_status}",
            metadata={
                "strategy_id": updated["id"],
                "name": updated["name"],
                "version": updated["version"],
                "from_status": from_status,
                "to_status": to_status,
                "operator": str(operator or "system"),
                "force": bool(force),
                "demoted_ids": demoted_ids,
                "gate_passed": bool(evaluation.get("passed", True)) if isinstance(evaluation, dict) else bool(force),
            },
        )
        return {
            "strategy": updated,
            "from_status": from_status,
            "to_status": to_status,
            "operator": str(operator or "system"),
            "force": bool(force),
            "gate": evaluation or {},
            "demoted_ids": demoted_ids,
        }

    def promote_strategy_version(
        self,
        strategy_id: str,
        *,
        operator: str = "system",
        force: bool = False,
        gate_result: dict[str, Any] | None = None,
        gate_overrides: dict[str, Any] | None = None,
        market: str = "",
        strategy_template: str = "",
    ) -> dict[str, Any]:
        result = self.transition_strategy_status(
            strategy_id,
            target_status="active",
            operator=operator,
            force=force,
            gate_result=gate_result,
            gate_overrides=gate_overrides,
            market=market,
            strategy_template=strategy_template,
        )
        promoted = dict(result.get("strategy", {}))
        self._record_audit(
            action="STRATEGY_PROMOTED",
            detail=f"strategy={promoted.get('name', '')} version={promoted.get('version', 0)}",
            metadata={
                "strategy_id": promoted.get("id", ""),
                "name": promoted.get("name", ""),
                "version": promoted.get("version", 0),
                "operator": str(operator or "system"),
                "force": bool(force),
                "demoted_ids": result.get("demoted_ids", []),
                "gate_passed": bool((result.get("gate", {}) or {}).get("passed", True))
                if isinstance(result.get("gate", {}), dict)
                else bool(force),
            },
        )
        return result

    def archive_backtest_report(
        self,
        *,
        strategy_id: str,
        report: dict[str, Any],
        market: str = "",
        strategy_template: str = "",
        run_tag: str = "",
        source: str = "api",
        bars_hash: str = "",
        params_hash: str = "",
        trace_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        strategy = self.get_strategy(strategy_id)
        strategy_params = strategy.get("parameters", {}) if isinstance(strategy.get("parameters", {}), dict) else {}
        payload = dict(report or {})
        metrics = payload.get("metrics", {}) if isinstance(payload.get("metrics", {}), dict) else {}
        summary = payload.get("summary", {}) if isinstance(payload.get("summary", {}), dict) else {}

        resolved_market = self._normalize_market(
            market
            or payload.get("market", "")
            or metrics.get("market", "")
            or strategy_params.get("market", ""),
            default="CN",
        )
        resolved_template = self._normalize_template(
            strategy_template
            or payload.get("strategy_template", "")
            or metrics.get("strategy_template", "")
            or strategy_params.get("strategy_template", "")
            or strategy_params.get("template", ""),
            default="default",
        )
        normalized_run_tag = self._normalize_run_tag(run_tag)
        normalized_source = str(source or "api").strip().lower() or "api"

        trace_ctx = dict(trace_context or {})
        normalized_bars_hash = str(bars_hash or "").strip() or self._hash_payload(trace_ctx.get("bars", []))
        normalized_params_hash = str(params_hash or "").strip() or self._hash_payload(trace_ctx.get("parameters", {}))

        report_id = str(uuid.uuid4())
        created_at = time.time()
        trace_index = {
            "report_id": report_id,
            "strategy_id": strategy["id"],
            "strategy_name": strategy["name"],
            "strategy_version": strategy["version"],
            "market": resolved_market,
            "strategy_template": resolved_template,
            "run_tag": normalized_run_tag,
            "source": normalized_source,
            "created_at": created_at,
            "trade_count": int(metrics.get("trade_count", 0) or 0),
            "win_rate": round(_to_float(metrics.get("win_rate", 0.0), 0.0), 6),
            "max_drawdown": round(_to_float(metrics.get("max_drawdown", 0.0), 0.0), 6),
            "net_pnl": round(_to_float(metrics.get("net_pnl", 0.0), 0.0), 6),
            "bars": int(summary.get("bars", 0) or 0),
            "bars_hash": normalized_bars_hash,
            "params_hash": normalized_params_hash,
        }
        report_payload = {
            "backtest": payload,
            "trace_context": trace_ctx,
            "trace_index": trace_index,
        }

        with self._db_factory() as db:
            db.execute(
                """
                INSERT INTO strategy_backtest_reports
                (id, strategy_id, strategy_name, strategy_version, market, strategy_template,
                 run_tag, source, bars_hash, params_hash, metrics, summary, trace_index, report_payload, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report_id,
                    strategy["id"],
                    strategy["name"],
                    int(strategy["version"]),
                    resolved_market,
                    resolved_template,
                    normalized_run_tag,
                    normalized_source,
                    normalized_bars_hash,
                    normalized_params_hash,
                    _to_json(metrics),
                    _to_json(summary),
                    _to_json(trace_index),
                    _to_json(report_payload),
                    created_at,
                ),
            )

        self._record_audit(
            action="STRATEGY_BACKTEST_ARCHIVED",
            detail=f"strategy={strategy['name']} version={strategy['version']}",
            metadata={
                "report_id": report_id,
                "strategy_id": strategy["id"],
                "market": resolved_market,
                "strategy_template": resolved_template,
                "run_tag": normalized_run_tag,
                "source": normalized_source,
            },
        )
        return {
            "id": report_id,
            "strategy_id": strategy["id"],
            "strategy_name": strategy["name"],
            "strategy_version": int(strategy["version"]),
            "market": resolved_market,
            "strategy_template": resolved_template,
            "run_tag": normalized_run_tag,
            "source": normalized_source,
            "bars_hash": normalized_bars_hash,
            "params_hash": normalized_params_hash,
            "metrics": metrics,
            "summary": summary,
            "trace_index": trace_index,
            "created_at": created_at,
        }

    def list_backtest_reports(
        self,
        *,
        strategy_id: str = "",
        strategy_name: str = "",
        market: str = "",
        strategy_template: str = "",
        run_tag: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if str(strategy_id or "").strip():
            clauses.append("strategy_id = ?")
            params.append(str(strategy_id).strip())
        if str(strategy_name or "").strip():
            clauses.append("strategy_name = ?")
            params.append(str(strategy_name).strip())
        if str(market or "").strip():
            clauses.append("market = ?")
            params.append(self._normalize_market(market))
        if str(strategy_template or "").strip():
            clauses.append("strategy_template = ?")
            params.append(self._normalize_template(strategy_template))
        if str(run_tag or "").strip():
            clauses.append("run_tag = ?")
            params.append(self._normalize_run_tag(run_tag))
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        sql = (
            "SELECT id, strategy_id, strategy_name, strategy_version, market, strategy_template, run_tag, source, "
            "bars_hash, params_hash, metrics, summary, trace_index, created_at "
            f"FROM strategy_backtest_reports {where_sql} ORDER BY created_at DESC LIMIT ?"
        )
        params.append(max(1, min(500, int(limit))))
        with self._db_factory() as db:
            rows = db.execute(sql, tuple(params)).fetchall()
        return [self._backtest_row_to_dict(row, include_payload=False) for row in rows]

    def get_backtest_report(self, report_id: str) -> dict[str, Any]:
        rid = str(report_id or "").strip()
        if not rid:
            raise TradingServiceError(
                code="INVALID_STRATEGY_REQUEST",
                message="report_id is required",
                http_status=400,
            )
        with self._db_factory() as db:
            row = db.execute(
                """
                SELECT id, strategy_id, strategy_name, strategy_version, market, strategy_template, run_tag, source,
                       bars_hash, params_hash, metrics, summary, trace_index, created_at, report_payload
                FROM strategy_backtest_reports
                WHERE id = ?
                """,
                (rid,),
            ).fetchone()
        if not row:
            raise TradingServiceError(
                code="STRATEGY_BACKTEST_REPORT_NOT_FOUND",
                message="backtest report not found",
                details={"report_id": rid},
                http_status=404,
            )
        return self._backtest_row_to_dict(row, include_payload=True)

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        return {
            "id": str(row[0] or ""),
            "name": str(row[1] or ""),
            "version": int(row[2] or 0),
            "parent_id": str(row[3] or ""),
            "origin": str(row[4] or ""),
            "content": str(row[5] or ""),
            "parameters": _from_json(row[6]),
            "metrics": _from_json(row[7]),
            "status": str(row[8] or ""),
            "created_at": _to_float(row[9], 0.0),
            "updated_at": _to_float(row[10], 0.0),
        }

    @staticmethod
    def _backtest_row_to_dict(row: Any, *, include_payload: bool) -> dict[str, Any]:
        result = {
            "id": str(row[0] or ""),
            "strategy_id": str(row[1] or ""),
            "strategy_name": str(row[2] or ""),
            "strategy_version": int(row[3] or 0),
            "market": str(row[4] or ""),
            "strategy_template": str(row[5] or ""),
            "run_tag": str(row[6] or ""),
            "source": str(row[7] or ""),
            "bars_hash": str(row[8] or ""),
            "params_hash": str(row[9] or ""),
            "metrics": _from_json(row[10]),
            "summary": _from_json(row[11]),
            "trace_index": _from_json(row[12]),
            "created_at": _to_float(row[13], 0.0),
        }
        if include_payload:
            result["report_payload"] = _from_json(row[14])
        return result

    @staticmethod
    def _record_audit(*, action: str, detail: str, metadata: dict[str, Any]) -> None:
        try:
            TradingLedger.record_entry(
                LedgerEntry(
                    category="EVOLUTION",
                    level="INFO",
                    action=action,
                    detail=detail,
                    status="success",
                    metadata=metadata,
                )
            )
        except Exception:
            return
