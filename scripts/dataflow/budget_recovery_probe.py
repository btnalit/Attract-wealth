from __future__ import annotations

import argparse
import json
import os
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


class _ProbeVM:
    async def run(self, ticker: str, initial_context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "session_id": "probe-session",
            "ticker": ticker,
            "messages": [],
            "current_agent": "probe",
            "decision": "HOLD",
            "confidence": 0.0,
            "analysis_reports": {},
            "context": initial_context or {},
            "trading_decision": {"action": "HOLD", "percentage": 0, "reason": "probe", "confidence": 0.0},
        }


class _ProbeBroker:
    channel_name = "simulation"

    @property
    def is_connected(self) -> bool:
        return True


def _default_output_path() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("data") / "stability" / f"budget_recovery_probe_{stamp}.json"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Budget recovery guard probe and report generator.")
    parser.add_argument("--cycles", type=int, default=30, help="Number of exceed/recover cycles.")
    parser.add_argument("--active-steps", type=int, default=2, help="Steps per cycle in budget exceeded state.")
    parser.add_argument("--recovery-steps", type=int, default=3, help="Steps per cycle in budget recovery state.")
    parser.add_argument("--interval-ms", type=int, default=120, help="Step interval in milliseconds.")
    parser.add_argument("--budget-usd", type=float, default=1.0)
    parser.add_argument("--exceed-cost", type=float, default=1.2)
    parser.add_argument("--recover-cost", type=float, default=0.6)
    parser.add_argument("--recovery-ratio", type=float, default=0.8)
    parser.add_argument("--cooldown-s", type=float, default=0.2)
    parser.add_argument("--action", choices=["force_hold", "warn_only", "none"], default="force_hold")
    parser.add_argument("--min-success-rate", type=float, default=0.95)
    parser.add_argument("--max-avg-recovery-s", type=float, default=5.0)
    parser.add_argument("--output", default="")
    return parser.parse_args()


@contextmanager
def _temporary_env(overrides: dict[str, str]) -> Iterator[None]:
    previous: dict[str, str | None] = {}
    for key, value in overrides.items():
        previous[key] = os.getenv(key)
        os.environ[key] = value
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _build_state(*, ticker: str, cost_usd: float, step_id: int) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "trace_id": f"probe-trace-{step_id}",
        "session_id": "probe-session",
        "context": {
            "realtime": {"price": 10.0},
            "news_sentiment": {"status": "ok", "sentiment_score": 50.0},
            "llm_runtime": {"last_flags": []},
            "llm_usage_summary": {"cost_usd": round(float(cost_usd), 6)},
        },
    }


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(max(0.0, float(item)) for item in values)
    if len(ordered) == 1:
        return round(ordered[0], 6)
    index = int(round((len(ordered) - 1) * 0.95))
    index = max(0, min(len(ordered) - 1, index))
    return round(ordered[index], 6)


def _evaluate_gate(args: argparse.Namespace, summary: dict[str, Any]) -> dict[str, Any]:
    failed_rules: list[dict[str, Any]] = []
    warn_rules: list[dict[str, Any]] = []

    activation_count = int(summary.get("activation_count", 0))
    success_rate = float(summary.get("recovery_success_rate", 0.0))
    avg_recovery = float(summary.get("avg_recovery_duration_s", 0.0))

    if activation_count <= 0:
        failed_rules.append(
            {
                "rule": "activation_count",
                "detail": "no budget guard activation observed; probe inputs may be invalid",
                "level": "block",
            }
        )

    if args.min_success_rate >= 0 and success_rate < args.min_success_rate:
        failed_rules.append(
            {
                "rule": "recovery_success_rate",
                "detail": (
                    f"recovery_success_rate={success_rate:.6f} below min_success_rate={float(args.min_success_rate):.6f}"
                ),
                "level": "block",
            }
        )

    if args.max_avg_recovery_s >= 0 and avg_recovery > args.max_avg_recovery_s:
        failed_rules.append(
            {
                "rule": "avg_recovery_duration_s",
                "detail": (
                    f"avg_recovery_duration_s={avg_recovery:.6f} exceeds max_avg_recovery_s="
                    f"{float(args.max_avg_recovery_s):.6f}"
                ),
                "level": "block",
            }
        )

    if activation_count > 0 and success_rate < 1.0:
        warn_rules.append(
            {
                "rule": "partial_recovery",
                "detail": "not all activations reached auto_recovered release",
                "level": "warn",
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
    output_path = Path(args.output).expanduser() if args.output else _default_output_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cycles = max(1, int(args.cycles))
    active_steps = max(1, int(args.active_steps))
    recovery_steps = max(1, int(args.recovery_steps))
    interval_s = max(0.0, int(args.interval_ms) / 1000.0)

    env_overrides = {
        "TRADE_DEGRADE_POLICY_ENABLED": "true",
        "TRADE_DEGRADE_MIN_MATCHES": "1",
        "TRADE_DEGRADE_ENABLED_RULES": "llm_daily_budget_exceeded",
        "TRADE_DEGRADE_LLM_BUDGET_ACTION": str(args.action),
        "TRADE_BUDGET_RECOVERY_ENABLED": "true",
        "TRADE_BUDGET_RECOVERY_RATIO": str(float(args.recovery_ratio)),
        "TRADE_BUDGET_RECOVERY_COOLDOWN_S": str(float(args.cooldown_s)),
        "TRADE_BUDGET_RECOVERY_ACTION": str(args.action),
        "LLM_DAILY_BUDGET_USD": str(float(args.budget_usd)),
    }

    started_at = time.time()
    steps_total = 0
    events: list[dict[str, Any]] = []
    samples: list[dict[str, Any]] = []
    current_event: dict[str, Any] | None = None
    service: Any | None = None

    with _temporary_env(env_overrides):
        from src.core import trading_service as ts_module
        from src.core.trading_service import TradingService

        original_record_entry = ts_module.TradingLedger.record_entry
        ts_module.TradingLedger.record_entry = staticmethod(lambda *args, **kwargs: None)
        try:
            service = TradingService(trading_channel="simulation", vm=_ProbeVM(), broker=_ProbeBroker())
            service._china_data_disabled = True

            for cycle_idx in range(1, cycles + 1):
                for phase, cost, repeat in (
                    ("exceed", float(args.exceed_cost), active_steps),
                    ("recover", float(args.recover_cost), recovery_steps),
                ):
                    for local_step in range(1, repeat + 1):
                        steps_total += 1
                        before_guard = service.get_budget_recovery_guard_state()
                        before_active = bool(before_guard.get("active", False))
                        state = _build_state(ticker="000001", cost_usd=cost, step_id=steps_total)
                        evaluation = service.degrade_policy.evaluate(state)
                        evaluation = service._apply_budget_recovery_guard(state, evaluation)
                        after_guard = evaluation.get("budget_recovery_guard", service.get_budget_recovery_guard_state())
                        after_active = bool(after_guard.get("active", False))

                        if (not before_active) and after_active:
                            if current_event is not None:
                                current_event["closed"] = False
                                events.append(current_event)
                            current_event = {
                                "cycle": cycle_idx,
                                "activated_at": after_guard.get("activated_at"),
                                "released_at": None,
                                "release_reason": "",
                                "recovery_duration_s": None,
                                "success": False,
                            }

                        if before_active and (not after_active) and current_event is not None:
                            metrics = after_guard.get("metrics", {}) if isinstance(after_guard, dict) else {}
                            duration_s = float(metrics.get("last_release_duration_s", 0.0))
                            reason = str(after_guard.get("release_reason", ""))
                            current_event["released_at"] = after_guard.get("released_at")
                            current_event["release_reason"] = reason
                            current_event["recovery_duration_s"] = duration_s
                            current_event["success"] = reason == "auto_recovered"
                            current_event["closed"] = True
                            events.append(current_event)
                            current_event = None

                        sample = {
                            "step": steps_total,
                            "cycle": cycle_idx,
                            "phase": phase,
                            "phase_step": local_step,
                            "cost_usd": round(cost, 6),
                            "active": after_active,
                            "release_reason": str(after_guard.get("release_reason", "")),
                            "recommended_action": str(evaluation.get("recommended_action", "")),
                            "should_degrade": bool(evaluation.get("should_degrade", False)),
                            "degrade_flags": list(evaluation.get("degrade_flags", [])),
                        }
                        samples.append(sample)
                        if interval_s > 0:
                            time.sleep(interval_s)
        finally:
            ts_module.TradingLedger.record_entry = original_record_entry

    if current_event is not None:
        current_event["closed"] = False
        events.append(current_event)

    if service is None:
        raise RuntimeError("probe service initialization failed")
    guard_state = service.get_budget_recovery_guard_state()
    metrics = guard_state.get("metrics", {}) if isinstance(guard_state.get("metrics", {}), dict) else {}
    durations = [float(item.get("recovery_duration_s", 0.0)) for item in events if bool(item.get("success", False))]
    summary = {
        "cycles": cycles,
        "steps_total": steps_total,
        "activation_count": int(metrics.get("activation_count", 0)),
        "release_count": int(metrics.get("release_count", 0)),
        "recovery_success_count": int(metrics.get("auto_recovery_success_count", 0)),
        "recovery_success_rate": float(metrics.get("recovery_success_rate", 0.0)),
        "avg_recovery_duration_s": float(metrics.get("avg_recovery_duration_s", 0.0)),
        "p95_recovery_duration_s": _p95(durations),
        "active_elapsed_s": float(metrics.get("active_elapsed_s", 0.0)),
    }
    gate = _evaluate_gate(args, summary)
    duration_ms = round((time.time() - started_at) * 1000.0, 3)

    report = {
        "report_version": "1.0",
        "generated_at": datetime.now().isoformat(),
        "duration_ms": duration_ms,
        "params": {
            "cycles": cycles,
            "active_steps": active_steps,
            "recovery_steps": recovery_steps,
            "interval_ms": int(args.interval_ms),
            "budget_usd": float(args.budget_usd),
            "exceed_cost": float(args.exceed_cost),
            "recover_cost": float(args.recover_cost),
            "recovery_ratio": float(args.recovery_ratio),
            "cooldown_s": float(args.cooldown_s),
            "action": str(args.action),
            "min_success_rate": float(args.min_success_rate),
            "max_avg_recovery_s": float(args.max_avg_recovery_s),
        },
        "summary": summary,
        "gate": gate,
        "guard_final": guard_state,
        "events": events,
        "samples_tail": samples[-30:],
    }

    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        "[budget-recovery-probe] output={output} status={status} success_rate={rate:.4f} avg_recovery_s={avg:.4f}".format(
            output=output_path,
            status=gate.get("status", "BLOCK"),
            rate=summary.get("recovery_success_rate", 0.0),
            avg=summary.get("avg_recovery_duration_s", 0.0),
        )
    )
    return 0 if gate.get("status", "BLOCK") != "BLOCK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
