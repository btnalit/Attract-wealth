from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.core.startup_preflight import run_startup_preflight


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run unified startup preflight checks.")
    parser.add_argument("--channel", default=os.getenv("TRADING_CHANNEL", "simulation"))
    parser.add_argument("--include-stability-probe", action="store_true")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when critical checks fail.")
    parser.add_argument("--output", default="data/smoke/reports/startup_preflight_latest.json")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    report = run_startup_preflight(
        channel=args.channel,
        include_stability_probe=bool(args.include_stability_probe),
    )
    output_path = Path(args.output).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = report.get("summary", {})
    print(
        "[startup-preflight] output={output} ok={ok} total={total} critical_failed={critical}".format(
            output=output_path,
            ok=report.get("ok", False),
            total=summary.get("total", 0),
            critical=summary.get("critical_failed", 0),
        )
    )
    if args.strict and not report.get("ok", False):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
