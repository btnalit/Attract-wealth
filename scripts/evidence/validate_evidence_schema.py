from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.core.trading_ledger import TradingLedger

REQUIRED_PATHS: tuple[str, ...] = (
    "payload.evidence_version",
    "payload.phase",
    "payload.timestamp",
    "payload.session_id",
    "payload.ticker",
    "payload.channel",
    "payload.decision",
    "payload.action",
    "payload.risk_check",
    "payload.trace",
    "payload.degrade_policy",
    "payload.budget_recovery_guard",
    "payload.reconciliation_guard",
    "payload.context_digest",
    "payload.llm_runtime",
    "payload.trace.trace_id",
    "payload.trace.request_id",
    "payload.trace.session_id",
    "payload.trace.phase",
    "payload.trace.channel",
    "payload.trace.ticker",
)

OPTIONAL_PATHS: tuple[str, ...] = (
    "payload.analysis_reports",
    "payload.degrade_flags",
    "payload.idempotency_key",
    "payload.client_order_id",
    "payload.status",
)

CONSISTENCY_RULES: tuple[tuple[str, str], ...] = (
    ("phase", "payload.phase"),
    ("phase", "payload.trace.phase"),
    ("session_id", "payload.session_id"),
    ("session_id", "payload.trace.session_id"),
    ("channel", "payload.channel"),
    ("channel", "payload.trace.channel"),
    ("ticker", "payload.ticker"),
    ("ticker", "payload.trace.ticker"),
    ("request_id", "payload.trace.request_id"),
    ("payload.request_id", "payload.trace.request_id"),
)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_output_path() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return ROOT_DIR / "data" / "evidence" / f"schema_validation_{stamp}.json"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate decision evidence required fields and trace consistency.")
    parser.add_argument("--limit", type=int, default=200, help="Scan latest N evidence rows.")
    parser.add_argument("--ticker", default="")
    parser.add_argument("--session-id", default="")
    parser.add_argument("--phase", default="")
    parser.add_argument("--request-id", default="")
    parser.add_argument("--degraded-only", action="store_true")
    parser.add_argument("--output", default="", help="Report output path.")
    parser.add_argument("--sample-size", type=int, default=20, help="Max sample rows in report.")
    parser.add_argument("--min-completeness-rate", type=float, default=0.95)
    parser.add_argument("--max-inconsistent-rate", type=float, default=0.02)
    parser.add_argument("--allow-empty", action="store_true", default=True)
    parser.add_argument("--disallow-empty", action="store_true")
    parser.add_argument("--fail-on-warn", action="store_true")
    parser.add_argument("--ignore-legacy", action="store_true", default=True, help="Skip rows without payload.evidence_version.")
    parser.add_argument("--no-ignore-legacy", action="store_true")
    parser.add_argument("--seed-sample-evidence", action="store_true", help="Insert strict-schema sample evidence before validation.")
    parser.add_argument("--sample-count", type=int, default=3, help="Sample evidence count when seeding.")
    return parser.parse_args()


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def _get_path(data: dict[str, Any], path: str) -> tuple[bool, Any]:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current.get(part)
    return True, current


def _to_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _compare_values(left: Any, right: Any) -> bool:
    if _is_missing(left) or _is_missing(right):
        return True
    return _to_string(left) == _to_string(right)


def _build_row_context(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload", {}) if isinstance(row.get("payload", {}), dict) else {}
    return {
        "id": row.get("id", ""),
        "timestamp": row.get("timestamp", 0.0),
        "phase": row.get("phase", ""),
        "session_id": row.get("session_id", ""),
        "request_id": row.get("request_id", ""),
        "trace_id": row.get("trace_id", ""),
        "ticker": row.get("ticker", ""),
        "channel": row.get("channel", ""),
        "decision": row.get("decision", ""),
        "action": row.get("action", ""),
        "payload": payload,
    }


def _seed_sample_rows(*, count: int) -> dict[str, Any]:
    now = time.time()
    request_id = f"schema-probe-{uuid.uuid4().hex[:12]}"
    seeded_ids: list[str] = []
    total = max(1, int(count))
    for index in range(total):
        evidence = {
            "evidence_version": "2026.04.08.1",
            "timestamp": now + index * 0.001,
            "phase": "execute",
            "session_id": f"{request_id}-sess",
            "request_id": request_id,
            "ticker": "000001",
            "channel": "simulation",
            "decision": "HOLD",
            "confidence": 0.0,
            "action": "HOLD",
            "percentage": 0.0,
            "reason": "schema_probe_seed",
            "risk_check": {"passed": True, "reason": "seed"},
            "order": {},
            "analysis_reports": {"technical": {"summary": "seed"}},
            "degrade_flags": [],
            "degrade_policy": {"policy_version": "seed"},
            "budget_recovery_guard": {"active": False, "metrics": {}},
            "reconciliation_guard": {"blocked": False, "ok_streak": 0},
            "trace": {
                "trace_id": f"{request_id}-trace-{index+1:03d}",
                "request_id": request_id,
                "session_id": f"{request_id}-sess",
                "phase": "execute",
                "channel": "simulation",
                "ticker": "000001",
            },
            "context_digest": {
                "portfolio": {},
                "realtime": {},
                "news_sentiment": {},
                "dataflow_quality": {},
                "dataflow_summary": {},
                "dataflow_tuning": {},
                "technical_keys": [],
                "fundamental_keys": [],
            },
            "llm_runtime": {"enabled": False, "provider": ""},
        }
        seeded_ids.append(TradingLedger.record_decision_evidence(evidence))
    return {"request_id": request_id, "seeded_ids": seeded_ids}


def _evaluate_records(
    rows: list[dict[str, Any]],
    *,
    sample_size: int,
    ignore_legacy: bool,
) -> dict[str, Any]:
    missing_required_counter: Counter[str] = Counter()
    missing_optional_counter: Counter[str] = Counter()
    inconsistent_counter: Counter[str] = Counter()
    incomplete_samples: list[dict[str, Any]] = []
    inconsistent_samples: list[dict[str, Any]] = []

    scanned_total = len(rows)
    skipped_legacy = 0
    total = 0
    complete = 0
    incomplete = 0
    inconsistent = 0

    for row in rows:
        ctx = _build_row_context(row)
        payload = ctx.get("payload", {}) if isinstance(ctx.get("payload", {}), dict) else {}
        if ignore_legacy and _is_missing(payload.get("evidence_version")):
            skipped_legacy += 1
            continue
        total += 1
        missing_required: list[str] = []
        missing_optional: list[str] = []
        row_inconsistencies: list[str] = []

        for path in REQUIRED_PATHS:
            found, value = _get_path(ctx, path)
            if (not found) or _is_missing(value):
                missing_required.append(path)
                missing_required_counter[path] += 1

        for path in OPTIONAL_PATHS:
            found, value = _get_path(ctx, path)
            if (not found) or _is_missing(value):
                missing_optional.append(path)
                missing_optional_counter[path] += 1

        for left_path, right_path in CONSISTENCY_RULES:
            left_found, left_value = _get_path(ctx, left_path)
            right_found, right_value = _get_path(ctx, right_path)
            if not left_found or not right_found:
                continue
            if not _compare_values(left_value, right_value):
                key = f"{left_path} == {right_path}"
                row_inconsistencies.append(key)
                inconsistent_counter[key] += 1

        row_incomplete = len(missing_required) > 0
        row_inconsistent = len(row_inconsistencies) > 0
        if row_incomplete:
            incomplete += 1
            if len(incomplete_samples) < sample_size:
                incomplete_samples.append(
                    {
                        "id": ctx["id"],
                        "phase": ctx["phase"],
                        "session_id": ctx["session_id"],
                        "request_id": ctx["request_id"],
                        "missing_required": missing_required,
                    }
                )
        if row_inconsistent:
            inconsistent += 1
            if len(inconsistent_samples) < sample_size:
                inconsistent_samples.append(
                    {
                        "id": ctx["id"],
                        "phase": ctx["phase"],
                        "session_id": ctx["session_id"],
                        "request_id": ctx["request_id"],
                        "trace_id": ctx["trace_id"],
                        "inconsistencies": row_inconsistencies,
                    }
                )
        if (not row_incomplete) and (not row_inconsistent):
            complete += 1

    completeness_rate = round((complete / total), 6) if total > 0 else 0.0
    inconsistent_rate = round((inconsistent / total), 6) if total > 0 else 0.0
    return {
        "counts": {
            "scanned_total": scanned_total,
            "skipped_legacy": skipped_legacy,
            "total": total,
            "complete": complete,
            "incomplete": incomplete,
            "inconsistent": inconsistent,
        },
        "rates": {
            "completeness_rate": completeness_rate,
            "inconsistent_rate": inconsistent_rate,
        },
        "missing_required": {
            "top": [{"path": key, "count": count} for key, count in missing_required_counter.most_common(20)],
            "total_unique_paths": len(missing_required_counter),
        },
        "missing_optional": {
            "top": [{"path": key, "count": count} for key, count in missing_optional_counter.most_common(20)],
            "total_unique_paths": len(missing_optional_counter),
        },
        "inconsistency": {
            "top": [{"rule": key, "count": count} for key, count in inconsistent_counter.most_common(20)],
            "total_unique_rules": len(inconsistent_counter),
        },
        "samples": {
            "incomplete": incomplete_samples,
            "inconsistent": inconsistent_samples,
        },
    }


def _evaluate_gate(args: argparse.Namespace, summary: dict[str, Any]) -> dict[str, Any]:
    failed_rules: list[dict[str, Any]] = []
    warn_rules: list[dict[str, Any]] = []

    counts = summary.get("counts", {}) if isinstance(summary.get("counts", {}), dict) else {}
    rates = summary.get("rates", {}) if isinstance(summary.get("rates", {}), dict) else {}
    total = int(counts.get("total", 0))
    skipped_legacy = int(counts.get("skipped_legacy", 0))
    completeness_rate = float(rates.get("completeness_rate", 0.0))
    inconsistent_rate = float(rates.get("inconsistent_rate", 0.0))
    min_completeness = max(0.0, min(1.0, float(args.min_completeness_rate)))
    max_inconsistent = max(0.0, min(1.0, float(args.max_inconsistent_rate)))

    if total <= 0:
        if args.allow_empty:
            warn_rules.append(
                {
                    "rule": "empty_rows",
                    "detail": "no evidence rows found under current filters",
                    "level": "warn",
                }
            )
        else:
            failed_rules.append(
                {
                    "rule": "empty_rows",
                    "detail": "no evidence rows found under current filters",
                    "level": "block",
                }
            )

    if skipped_legacy > 0:
        warn_rules.append(
            {
                "rule": "legacy_rows_skipped",
                "detail": f"skipped_legacy={skipped_legacy} rows without evidence_version",
                "level": "warn",
            }
        )

    if total > 0 and completeness_rate < min_completeness:
        failed_rules.append(
            {
                "rule": "completeness_rate",
                "detail": (
                    f"completeness_rate={completeness_rate:.6f} below "
                    f"min_completeness_rate={min_completeness:.6f}"
                ),
                "level": "block",
            }
        )

    if total > 0 and inconsistent_rate > max_inconsistent:
        failed_rules.append(
            {
                "rule": "inconsistent_rate",
                "detail": (
                    f"inconsistent_rate={inconsistent_rate:.6f} exceeds "
                    f"max_inconsistent_rate={max_inconsistent:.6f}"
                ),
                "level": "block",
            }
        )

    status = "BLOCK" if failed_rules else "WARN" if warn_rules else "PASS"
    return {
        "status": status,
        "failed_rules": failed_rules,
        "warn_rules": warn_rules,
    }


def main() -> int:
    args = _parse_args()
    if args.disallow_empty:
        args.allow_empty = False
    if args.no_ignore_legacy:
        args.ignore_legacy = False
    output_path = Path(args.output).expanduser() if args.output else _default_output_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    seed_info: dict[str, Any] = {"enabled": False, "request_id": "", "seeded_ids": []}
    request_filter = str(args.request_id or "")
    if args.seed_sample_evidence:
        seed_info = {"enabled": True, **_seed_sample_rows(count=max(1, int(args.sample_count)))}
        if not request_filter:
            request_filter = str(seed_info.get("request_id", ""))

    records = TradingLedger.list_decision_evidence(
        limit=max(1, int(args.limit)),
        ticker=str(args.ticker or ""),
        session_id=str(args.session_id or ""),
        phase=str(args.phase or ""),
        request_id=request_filter,
        degraded_only=bool(args.degraded_only),
    )
    summary = _evaluate_records(
        records,
        sample_size=max(1, int(args.sample_size)),
        ignore_legacy=bool(args.ignore_legacy),
    )
    gate = _evaluate_gate(args, summary)

    report = {
        "report_version": "1.0",
        "generated_at": _iso_now(),
        "params": {
            "limit": max(1, int(args.limit)),
            "ticker": str(args.ticker or ""),
            "session_id": str(args.session_id or ""),
            "phase": str(args.phase or ""),
            "request_id": request_filter,
            "degraded_only": bool(args.degraded_only),
            "sample_size": max(1, int(args.sample_size)),
            "min_completeness_rate": max(0.0, min(1.0, float(args.min_completeness_rate))),
            "max_inconsistent_rate": max(0.0, min(1.0, float(args.max_inconsistent_rate))),
            "allow_empty": bool(args.allow_empty),
            "fail_on_warn": bool(args.fail_on_warn),
            "ignore_legacy": bool(args.ignore_legacy),
            "seed_sample_evidence": bool(args.seed_sample_evidence),
            "sample_count": max(1, int(args.sample_count)),
        },
        "seed": seed_info,
        "required_paths": list(REQUIRED_PATHS),
        "optional_paths": list(OPTIONAL_PATHS),
        "consistency_rules": [{"left": left, "right": right} for left, right in CONSISTENCY_RULES],
        "summary": summary,
        "gate": gate,
    }
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        "[evidence-schema] output={output} status={status} total={total} completeness={complete:.4f} inconsistent={incons:.4f}".format(
            output=output_path,
            status=gate.get("status", "BLOCK"),
            total=summary.get("counts", {}).get("total", 0),
            complete=summary.get("rates", {}).get("completeness_rate", 0.0),
            incons=summary.get("rates", {}).get("inconsistent_rate", 0.0),
        )
    )

    status = str(gate.get("status", "BLOCK")).upper()
    if status == "BLOCK":
        return 1
    if status == "WARN" and args.fail_on_warn:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
