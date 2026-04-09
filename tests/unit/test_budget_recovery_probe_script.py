from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_module():
    root = Path(__file__).resolve().parents[2]
    module_path = root / "scripts" / "dataflow" / "budget_recovery_probe.py"
    spec = importlib.util.spec_from_file_location("budget_recovery_probe", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_budget_recovery_probe_generates_report(monkeypatch):
    module = _load_module()
    output = module.ROOT_DIR / "_pytest_tmp" / "budget_recovery_probe_report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "budget_recovery_probe.py",
            "--cycles",
            "4",
            "--active-steps",
            "1",
            "--recovery-steps",
            "2",
            "--interval-ms",
            "0",
            "--cooldown-s",
            "0",
            "--min-success-rate",
            "1.0",
            "--max-avg-recovery-s",
            "1.0",
            "--output",
            str(output),
        ],
    )
    rc = module.main()
    assert rc == 0
    assert output.exists()

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["gate"]["status"] == "PASS"
    assert payload["summary"]["activation_count"] >= 1
    assert payload["summary"]["recovery_success_rate"] == 1.0
    assert payload["summary"]["avg_recovery_duration_s"] >= 0.0


def test_budget_recovery_probe_blocks_on_low_recovery(monkeypatch):
    module = _load_module()
    output = module.ROOT_DIR / "_pytest_tmp" / "budget_recovery_probe_block_report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "budget_recovery_probe.py",
            "--cycles",
            "3",
            "--active-steps",
            "1",
            "--recovery-steps",
            "1",
            "--interval-ms",
            "0",
            "--cooldown-s",
            "0",
            "--recover-cost",
            "0.95",
            "--min-success-rate",
            "0.5",
            "--output",
            str(output),
        ],
    )
    rc = module.main()
    assert rc == 1
    assert output.exists()

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["gate"]["status"] == "BLOCK"
    rules = payload["gate"]["failed_rules"]
    assert any(item["rule"] == "recovery_success_rate" for item in rules)
