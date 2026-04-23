from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

class _FlakyProvider:
    def __init__(self, failure_every: int = 4):
        self.failure_every = max(1, int(failure_every))
        self.calls = 0

    def get_kline(self, ticker: str, start_date: str, end_date: str, timeframe: str = "D") -> Any:
        return [{"date": "2026-04-08", "close": 10.0}]

    def get_fundamentals(self, ticker: str) -> dict:
        return {"ticker": ticker}

    def get_news(self, ticker: str, limit: int = 10) -> list[dict]:
        self.calls += 1
        if self.calls % self.failure_every == 0:
            raise RuntimeError("simulated upstream failure")
        return [{"ticker": ticker, "title": f"{ticker}-ok", "limit": limit}]


class _StableProvider:
    def get_kline(self, ticker: str, start_date: str, end_date: str, timeframe: str = "D") -> Any:
        return [{"date": "2026-04-08", "close": 10.0}]

    def get_fundamentals(self, ticker: str) -> dict:
        return {"ticker": ticker}

    def get_news(self, ticker: str, limit: int = 10) -> list[dict]:
        return [{"ticker": ticker, "title": f"{ticker}-stable", "limit": limit}]


def _default_report_path() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("data") / "stability" / f"dataflow_probe_{stamp}.json"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dataflow stability probe with fallback/retry/ratelimit metrics.")
    parser.add_argument("--iterations", type=int, default=80)
    parser.add_argument("--failure-every", type=int, default=9)
    parser.add_argument("--sleep-ms", type=int, default=0)
    parser.add_argument("--rate-limit-per-minute", type=int, default=90)
    parser.add_argument("--max-wait-ms", type=int, default=0)
    parser.add_argument("--retry-count", type=int, default=2)
    parser.add_argument("--retry-base-ms", type=int, default=30)
    parser.add_argument("--fail-on-quality", choices=["none", "warn", "critical"], default="critical")
    parser.add_argument("--max-retry-rate", type=float, default=-1.0)
    parser.add_argument("--max-rate-limited-rate", type=float, default=-1.0)
    parser.add_argument("--max-error-rate", type=float, default=-1.0)
    parser.add_argument("--output", default="")
    return parser.parse_args()


def _apply_env(args: argparse.Namespace) -> None:
    os.environ["DATA_PROVIDER_RATE_LIMIT_PER_MINUTE"] = str(args.rate_limit_per_minute)
    os.environ["DATA_PROVIDER_MIN_INTERVAL_MS"] = "0"
    os.environ["DATA_PROVIDER_MAX_WAIT_MS"] = str(max(0, args.max_wait_ms))
    os.environ["DATA_PROVIDER_BACKOFF_RETRIES"] = str(max(0, args.retry_count))
    os.environ["DATA_PROVIDER_BACKOFF_BASE_MS"] = str(max(0, args.retry_base_ms))
    os.environ["DATA_PROVIDER_BACKOFF_MAX_MS"] = str(max(1, args.retry_base_ms * 8))
    # Probe uses synthetic providers only; disable default akshare bootstrap noise.
    os.environ["DATA_SOURCE_BOOTSTRAP_AKSHARE"] = "false"


def _evaluate_gate(args: argparse.Namespace, metrics: dict[str, Any]) -> dict[str, Any]:
    summary = metrics.get("summary", {})
    quality = metrics.get("quality", {})
    quality_level = str(quality.get("alert_level", "none"))

    failed_rules: list[dict[str, Any]] = []
    warn_rules: list[dict[str, Any]] = []

    def _add_rule(name: str, detail: str, *, level: str) -> None:
        row = {"rule": name, "detail": detail, "level": level}
        if level == "block":
            failed_rules.append(row)
        else:
            warn_rules.append(row)

    if args.fail_on_quality == "critical" and quality_level == "critical":
        _add_rule("quality_level", f"quality={quality_level} hit fail_on={args.fail_on_quality}", level="block")
    elif args.fail_on_quality == "warn" and quality_level in {"warn", "critical"}:
        _add_rule("quality_level", f"quality={quality_level} hit fail_on={args.fail_on_quality}", level="block")
    elif quality_level == "warn":
        _add_rule("quality_level", "quality level is warn", level="warn")

    retry_rate = float(summary.get("retry_rate", 0.0))
    rate_limited_rate = float(summary.get("rate_limited_rate", 0.0))
    error_rate = float(summary.get("error_rate", 0.0))

    if args.max_retry_rate >= 0 and retry_rate > args.max_retry_rate:
        _add_rule(
            "retry_rate",
            f"retry_rate={retry_rate:.4f} exceeds max_retry_rate={args.max_retry_rate:.4f}",
            level="block",
        )
    if args.max_rate_limited_rate >= 0 and rate_limited_rate > args.max_rate_limited_rate:
        _add_rule(
            "rate_limited_rate",
            (
                "rate_limited_rate="
                f"{rate_limited_rate:.4f} exceeds max_rate_limited_rate={args.max_rate_limited_rate:.4f}"
            ),
            level="block",
        )
    if args.max_error_rate >= 0 and error_rate > args.max_error_rate:
        _add_rule(
            "error_rate",
            f"error_rate={error_rate:.4f} exceeds max_error_rate={args.max_error_rate:.4f}",
            level="block",
        )

    status = "BLOCK" if failed_rules else "WARN" if warn_rules else "PASS"
    return {
        "status": status,
        "quality_level": quality_level,
        "failed_rules": failed_rules,
        "warn_rules": warn_rules,
    }


def main() -> int:
    args = _parse_args()
    output_path = Path(args.output).expanduser() if args.output else _default_report_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    _apply_env(args)
    from src.dataflows.source_manager import DataSourceManager

    manager = DataSourceManager(cache=None)
    manager.register("flaky", _FlakyProvider(failure_every=args.failure_every), priority=10, is_primary=True)
    manager.register("stable", _StableProvider(), priority=20)

    started = time.perf_counter()
    success = 0
    failed = 0
    for idx in range(max(1, args.iterations)):
        rows = manager.get_news("000001", limit=(idx % 5) + 1)
        if rows:
            success += 1
        else:
            failed += 1
        if args.sleep_ms > 0:
            time.sleep(args.sleep_ms / 1000.0)

    metrics = manager.get_metrics()
    gate = _evaluate_gate(args, metrics)
    duration_ms = round((time.perf_counter() - started) * 1000, 3)

    report = {
        "report_version": "1.1",
        "started_at": datetime.now().isoformat(),
        "duration_ms": duration_ms,
        "iterations": args.iterations,
        "success_count": success,
        "failed_count": failed,
        "metrics": metrics,
        "summary": metrics.get("summary", {}),
        "quality": metrics.get("quality", {}),
        "tuning": metrics.get("tuning", {}),
        "gate": gate,
    }

    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[stability] output={output_path}")
    print(
        "[stability] status={status} quality={quality} retry_rate={retry_rate} rate_limited_rate={rl_rate}".format(
            status=gate["status"],
            quality=gate["quality_level"],
            retry_rate=report["summary"].get("retry_rate", 0.0),
            rl_rate=report["summary"].get("rate_limited_rate", 0.0),
        )
    )
    return 1 if gate["status"] == "BLOCK" else 0


if __name__ == "__main__":
    raise SystemExit(main())
