from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_module():
    root = Path(__file__).resolve().parents[2]
    module_path = root / "scripts" / "smoke" / "run_channel_matrix.py"
    spec = importlib.util.spec_from_file_location("run_channel_matrix", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_main_collects_budget_probe_and_blocks_gate(monkeypatch):
    module = _load_module()
    temp_dir = Path(__file__).resolve().parents[2] / "_pytest_tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    output = temp_dir / "matrix_budget_probe_test.json"
    output.unlink(missing_ok=True)

    monkeypatch.setattr(
        module,
        "_run_channel",
        lambda args, channel, report_path: {
            "channel": channel,
            "status": "PASS",
            "gate_ok": True,
            "returncode": 0,
            "report": str(report_path),
            "stdout": "",
            "stderr": "",
            "checks": [],
            "preflight": {},
        },
    )
    monkeypatch.setattr(
        module,
        "_run_stability_probe",
        lambda args, report_path: {
            "enabled": True,
            "status": "PASS",
            "gate_ok": True,
            "returncode": 0,
            "report": str(report_path),
            "stdout": "",
            "stderr": "",
            "summary": {},
            "quality": {},
            "tuning": {},
            "gate": {},
        },
    )
    monkeypatch.setattr(
        module,
        "_run_budget_recovery_probe",
        lambda args, report_path: {
            "enabled": True,
            "status": "BLOCK",
            "gate_ok": False,
            "returncode": 1,
            "report": str(report_path),
            "stdout": "",
            "stderr": "",
            "summary": {"recovery_success_rate": 0.8},
            "params": {},
            "gate": {"failed_rules": [{"rule": "recovery_success_rate", "detail": "too low"}]},
        },
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_channel_matrix.py",
            "--channels",
            "ths_ipc,simulation",
            "--with-stability-probe",
            "--with-budget-recovery-probe",
            "--output",
            str(output),
        ],
    )
    rc = module.main()
    assert rc == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["all_passed"] is False
    assert payload["budget_recovery_probe"]["enabled"] is True
    assert payload["budget_recovery_probe"]["status"] == "BLOCK"
