from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable


def _is_true(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _split_csv(raw: str | None) -> set[str]:
    if not raw:
        return set()
    return {item.strip().lower() for item in str(raw).split(",") if item.strip()}


def _normalize_action(action: str | None, *, default: str = "force_hold") -> str:
    value = str(action or "").strip().lower()
    if value in {"force_hold", "warn_only", "none"}:
        return value
    return default


ACTION_RANK: dict[str, int] = {
    "none": 0,
    "warn_only": 1,
    "force_hold": 2,
}


def _collect_analyst_llm_fallback_count(state: dict[str, Any]) -> int:
    reports = state.get("analysis_reports", {}) if isinstance(state, dict) else {}
    count = 0
    if not isinstance(reports, dict):
        return count

    for value in reports.values():
        payload = (
            value.model_dump()
            if hasattr(value, "model_dump")
            else value.dict()
            if hasattr(value, "dict")
            else value
        )
        if not isinstance(payload, dict):
            continue
        summary = str(payload.get("summary", "")).lower()
        factors = [str(item).lower() for item in payload.get("key_factors", [])]
        if "llm fallback" in summary or "llm failure" in factors:
            count += 1
    return count


@dataclass(frozen=True)
class DegradeRule:
    rule_id: str
    description: str
    severity: str
    action: str
    priority: int
    evaluator: Callable[[dict[str, Any]], tuple[bool, str]]
    enabled: bool = True


class DegradePolicyMatrix:
    """Centralized degradation policy evaluator."""

    def __init__(
        self,
        *,
        policy_name: str,
        policy_version: str,
        enabled: bool,
        min_matches: int,
        conflict_strategy: str,
        rules: list[DegradeRule],
    ):
        self.policy_name = str(policy_name)
        self.policy_version = str(policy_version)
        self.enabled = bool(enabled)
        self.min_matches = max(1, int(min_matches))
        self.conflict_strategy = self._normalize_conflict_strategy(conflict_strategy)
        self.rules = list(rules)

    @staticmethod
    def _normalize_conflict_strategy(value: str | None) -> str:
        raw = str(value or "").strip().lower()
        if raw in {"highest_priority", "highest_action", "all"}:
            return raw
        return "highest_priority"

    @staticmethod
    def _pick_recommended_action(rules: list[dict[str, Any]]) -> str:
        if not rules:
            return "none"
        recommended_action = max(
            (str(item.get("action", "none")) for item in rules),
            key=lambda action: ACTION_RANK.get(_normalize_action(action, default="none"), 0),
            default="none",
        )
        return _normalize_action(recommended_action, default="none")

    def _resolve_conflict(self, matched_rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not matched_rules:
            return []

        sorted_rules = sorted(
            matched_rules,
            key=lambda item: (
                int(item.get("priority", 0)),
                ACTION_RANK.get(str(item.get("action", "none")), 0),
            ),
            reverse=True,
        )
        if self.conflict_strategy == "all":
            return sorted_rules

        if self.conflict_strategy == "highest_action":
            top_rank = max(
                (ACTION_RANK.get(str(row.get("action", "none")), 0) for row in sorted_rules),
                default=0,
            )
            selected = [row for row in sorted_rules if ACTION_RANK.get(str(row.get("action", "none")), 0) == top_rank]
            return selected

        # default: highest_priority
        top_priority = int(sorted_rules[0].get("priority", 0))
        selected = [row for row in sorted_rules if int(row.get("priority", 0)) == top_priority]
        return selected

    def resolve_conflict(self, matched_rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self._resolve_conflict(list(matched_rules or []))

    def summarize_decision(self, selected_rules: list[dict[str, Any]]) -> dict[str, Any]:
        recommended_action = self._pick_recommended_action(list(selected_rules or []))
        return {
            "recommended_action": recommended_action,
            "should_force_hold": recommended_action == "force_hold",
            "should_warn": recommended_action == "warn_only",
            "should_degrade": recommended_action in {"force_hold", "warn_only"},
        }

    def evaluate(self, state: dict[str, Any]) -> dict[str, Any]:
        evaluated = 0
        matched_rules: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []

        for rule in self.rules:
            if not rule.enabled:
                continue
            evaluated += 1
            try:
                matched, detail = rule.evaluator(state)
            except Exception as exc:  # noqa: BLE001
                errors.append({"rule_id": rule.rule_id, "error": str(exc)})
                continue
            if not matched:
                continue
            action = _normalize_action(rule.action, default="force_hold")
            matched_rules.append(
                {
                    "rule_id": rule.rule_id,
                    "description": rule.description,
                    "severity": rule.severity,
                    "action": action,
                    "priority": int(rule.priority),
                    "detail": detail,
                }
            )

        selected_rules: list[dict[str, Any]] = []
        recommended_action = "none"
        if self.enabled and len(matched_rules) >= self.min_matches:
            selected_rules = self._resolve_conflict(matched_rules)
            recommended_action = self._pick_recommended_action(selected_rules)

        summary = self.summarize_decision(selected_rules)
        degrade_flags = [item["rule_id"] for item in selected_rules]
        return {
            "policy_name": self.policy_name,
            "policy_version": self.policy_version,
            "enabled": self.enabled,
            "min_matches": self.min_matches,
            "conflict_strategy": self.conflict_strategy,
            "rules_evaluated": evaluated,
            "matched_count": len(matched_rules),
            "matched_rules": matched_rules,
            "selected_rules": selected_rules,
            "degrade_flags": degrade_flags,
            "recommended_action": summary["recommended_action"],
            "should_force_hold": summary["should_force_hold"],
            "should_warn": summary["should_warn"],
            "should_degrade": summary["should_degrade"],
            "errors": errors,
        }

    def describe(self) -> dict[str, Any]:
        return {
            "policy_name": self.policy_name,
            "policy_version": self.policy_version,
            "enabled": self.enabled,
            "min_matches": self.min_matches,
            "conflict_strategy": self.conflict_strategy,
            "rules": [
                {
                    "rule_id": rule.rule_id,
                    "description": rule.description,
                    "severity": rule.severity,
                    "action": rule.action,
                    "priority": int(rule.priority),
                    "enabled": rule.enabled,
                }
                for rule in self.rules
            ],
        }


def build_default_degrade_policy() -> DegradePolicyMatrix:
    policy_version = os.getenv("TRADE_DEGRADE_POLICY_VERSION", "2026.04.08.1").strip() or "2026.04.08.1"
    policy_enabled = _is_true(os.getenv("TRADE_DEGRADE_POLICY_ENABLED"), default=True)
    min_matches = int(os.getenv("TRADE_DEGRADE_MIN_MATCHES", "1"))
    conflict_strategy = os.getenv("TRADE_DEGRADE_CONFLICT_STRATEGY", "highest_priority")
    analyst_llm_threshold = max(1, int(os.getenv("TRADE_DEGRADE_ANALYST_LLM_FAIL_COUNT", "2")))
    dataflow_alert_levels = _split_csv(os.getenv("TRADE_DEGRADE_DATAFLOW_ALERT_LEVELS", "critical")) or {"critical"}
    llm_latency_action = _normalize_action(os.getenv("TRADE_DEGRADE_LLM_LATENCY_ACTION"), default="warn_only")
    llm_cost_action = _normalize_action(os.getenv("TRADE_DEGRADE_LLM_COST_ACTION"), default="warn_only")
    llm_budget_action = _normalize_action(os.getenv("TRADE_DEGRADE_LLM_BUDGET_ACTION"), default="force_hold")

    include_set = _split_csv(os.getenv("TRADE_DEGRADE_ENABLED_RULES", ""))
    exclude_set = _split_csv(os.getenv("TRADE_DEGRADE_DISABLED_RULES", ""))
    priority_overrides = _parse_priority_overrides(os.getenv("TRADE_DEGRADE_RULE_PRIORITIES", ""))

    def _enabled(rule_id: str) -> bool:
        rid = str(rule_id).strip().lower()
        if include_set and rid not in include_set:
            return False
        if rid in exclude_set:
            return False
        return True

    def _priority(rule_id: str, default: int) -> int:
        rid = str(rule_id).strip().lower()
        return int(priority_overrides.get(rid, default))

    def _rule_realtime_price(state: dict[str, Any]) -> tuple[bool, str]:
        context = state.get("context", {}) if isinstance(state, dict) else {}
        realtime = context.get("realtime", {}) if isinstance(context, dict) else {}
        price = _to_float(realtime.get("price", 0.0)) if isinstance(realtime, dict) else 0.0
        matched = price <= 0
        return matched, f"realtime.price={price}"

    def _rule_news_status(state: dict[str, Any]) -> tuple[bool, str]:
        context = state.get("context", {}) if isinstance(state, dict) else {}
        news = context.get("news_sentiment", {}) if isinstance(context, dict) else {}
        status = str(news.get("status", "")).strip().lower() if isinstance(news, dict) else ""
        matched = status.startswith("error")
        return matched, f"news.status={status}"

    def _rule_analyst_llm(state: dict[str, Any]) -> tuple[bool, str]:
        count = _collect_analyst_llm_fallback_count(state)
        matched = count >= analyst_llm_threshold
        return matched, f"fallback_count={count}, threshold={analyst_llm_threshold}"

    def _rule_trader_llm(state: dict[str, Any]) -> tuple[bool, str]:
        decision_reason = str(state.get("trading_decision", {}).get("reason", "")).lower()
        matched = "llm fallback" in decision_reason
        return matched, f"trading_decision.reason={decision_reason[:120]}"

    def _rule_manual_flag(state: dict[str, Any]) -> tuple[bool, str]:
        context = state.get("context", {}) if isinstance(state, dict) else {}
        flag = bool(context.get("degrade_to_hold", False)) if isinstance(context, dict) else False
        return flag, f"context.degrade_to_hold={flag}"

    def _rule_dataflow_quality(state: dict[str, Any]) -> tuple[bool, str]:
        context = state.get("context", {}) if isinstance(state, dict) else {}
        quality = context.get("dataflow_quality", {}) if isinstance(context, dict) else {}
        level = str(quality.get("alert_level", "")).strip().lower() if isinstance(quality, dict) else ""
        matched = bool(level and level in dataflow_alert_levels)
        levels = ",".join(sorted(list(dataflow_alert_levels)))
        return matched, f"dataflow.alert_level={level}, target_levels={levels}"

    def _rule_llm_latency_exceeded(state: dict[str, Any]) -> tuple[bool, str]:
        context = state.get("context", {}) if isinstance(state, dict) else {}
        runtime = context.get("llm_runtime", {}) if isinstance(context, dict) else {}
        flags = [str(item).strip().lower() for item in runtime.get("last_flags", [])] if isinstance(runtime, dict) else []
        count = int(runtime.get("latency_exceeded_count", 0)) if isinstance(runtime, dict) else 0
        matched = "latency_exceeded" in flags or count > 0
        return matched, f"llm.latency_exceeded_count={count}, last_flags={flags}"

    def _rule_llm_cost_exceeded(state: dict[str, Any]) -> tuple[bool, str]:
        context = state.get("context", {}) if isinstance(state, dict) else {}
        runtime = context.get("llm_runtime", {}) if isinstance(context, dict) else {}
        flags = [str(item).strip().lower() for item in runtime.get("last_flags", [])] if isinstance(runtime, dict) else []
        count = int(runtime.get("cost_exceeded_count", 0)) if isinstance(runtime, dict) else 0
        matched = "cost_per_call_exceeded" in flags or count > 0
        return matched, f"llm.cost_exceeded_count={count}, last_flags={flags}"

    def _rule_llm_budget_exceeded(state: dict[str, Any]) -> tuple[bool, str]:
        budget = _to_float(os.getenv("LLM_DAILY_BUDGET_USD", "0"))
        if budget <= 0:
            return False, "llm.daily_budget_disabled"
        context = state.get("context", {}) if isinstance(state, dict) else {}
        usage_summary = context.get("llm_usage_summary", {}) if isinstance(context, dict) else {}
        cost = _to_float(usage_summary.get("cost_usd", 0.0)) if isinstance(usage_summary, dict) else 0.0
        runtime = context.get("llm_runtime", {}) if isinstance(context, dict) else {}
        flags = [str(item).strip().lower() for item in runtime.get("last_flags", [])] if isinstance(runtime, dict) else []
        matched = cost >= budget or "daily_budget_exceeded" in flags
        return matched, f"llm.cost_usd={cost}, budget={budget}, last_flags={flags}"

    rules = [
        DegradeRule(
            rule_id="realtime_price_unavailable",
            description="实时价格不可用或无效。",
            severity="critical",
            action="force_hold",
            priority=_priority("realtime_price_unavailable", 90),
            evaluator=_rule_realtime_price,
            enabled=_enabled("realtime_price_unavailable"),
        ),
        DegradeRule(
            rule_id="news_status_error",
            description="新闻情绪数据源返回错误状态。",
            severity="warn",
            action="force_hold",
            priority=_priority("news_status_error", 30),
            evaluator=_rule_news_status,
            enabled=_enabled("news_status_error"),
        ),
        DegradeRule(
            rule_id="analyst_llm_degraded",
            description="分析师侧 LLM 回退次数超过阈值。",
            severity="warn",
            action="force_hold",
            priority=_priority("analyst_llm_degraded", 35),
            evaluator=_rule_analyst_llm,
            enabled=_enabled("analyst_llm_degraded"),
        ),
        DegradeRule(
            rule_id="trader_llm_fallback",
            description="交易员决策出现 LLM fallback 痕迹。",
            severity="warn",
            action="force_hold",
            priority=_priority("trader_llm_fallback", 40),
            evaluator=_rule_trader_llm,
            enabled=_enabled("trader_llm_fallback"),
        ),
        DegradeRule(
            rule_id="manual_degrade_flag",
            description="上下文手动触发降级标记。",
            severity="critical",
            action="force_hold",
            priority=_priority("manual_degrade_flag", 100),
            evaluator=_rule_manual_flag,
            enabled=_enabled("manual_degrade_flag"),
        ),
        DegradeRule(
            rule_id="dataflow_quality_critical",
            description="数据质量告警达到配置的降级级别。",
            severity="critical",
            action="force_hold",
            priority=_priority("dataflow_quality_critical", 85),
            evaluator=_rule_dataflow_quality,
            enabled=_enabled("dataflow_quality_critical"),
        ),
        DegradeRule(
            rule_id="llm_latency_exceeded",
            description="LLM 延迟超过治理阈值。",
            severity="warn",
            action=llm_latency_action,
            priority=_priority("llm_latency_exceeded", 45),
            evaluator=_rule_llm_latency_exceeded,
            enabled=_enabled("llm_latency_exceeded"),
        ),
        DegradeRule(
            rule_id="llm_cost_per_call_exceeded",
            description="LLM 单次调用成本超过阈值。",
            severity="warn",
            action=llm_cost_action,
            priority=_priority("llm_cost_per_call_exceeded", 55),
            evaluator=_rule_llm_cost_exceeded,
            enabled=_enabled("llm_cost_per_call_exceeded"),
        ),
        DegradeRule(
            rule_id="llm_daily_budget_exceeded",
            description="LLM 当日预算超限。",
            severity="critical",
            action=llm_budget_action,
            priority=_priority("llm_daily_budget_exceeded", 80),
            evaluator=_rule_llm_budget_exceeded,
            enabled=_enabled("llm_daily_budget_exceeded"),
        ),
    ]

    return DegradePolicyMatrix(
        policy_name="default_trade_degrade_policy",
        policy_version=policy_version,
        enabled=policy_enabled,
        min_matches=min_matches,
        conflict_strategy=conflict_strategy,
        rules=rules,
    )


def _parse_priority_overrides(raw: str | None) -> dict[str, int]:
    text = str(raw or "").strip()
    if not text:
        return {}

    mapping: dict[str, int] = {}
    for item in text.split(","):
        token = item.strip()
        if not token or ":" not in token:
            continue
        key, value = token.split(":", 1)
        rule_id = key.strip().lower()
        if not rule_id:
            continue
        try:
            mapping[rule_id] = int(value.strip())
        except ValueError:
            continue
    return mapping
