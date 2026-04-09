from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path


def _load_module():
    root = Path(__file__).resolve().parents[2]
    module_path = root / "scripts" / "smoke" / "run_oneclick_gate.py"
    spec = importlib.util.spec_from_file_location("run_oneclick_gate", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _build_args(*, no_stability_probe: bool, no_budget_recovery_probe: bool) -> argparse.Namespace:
    return argparse.Namespace(
        channels="ths_ipc,qmt",
        include_order_probe=True,
        force_live_order=False,
        no_reconcile=True,
        no_stability_probe=no_stability_probe,
        no_budget_recovery_probe=no_budget_recovery_probe,
        probe_iterations=80,
        probe_failure_every=4,
        probe_rate_limit_per_minute=90,
        probe_max_wait_ms=0,
        probe_retry_count=2,
        probe_retry_base_ms=30,
        probe_fail_on_quality="critical",
        budget_probe_cycles=7,
        budget_probe_active_steps=1,
        budget_probe_recovery_steps=2,
        budget_probe_interval_ms=0,
        budget_probe_budget_usd=1.0,
        budget_probe_exceed_cost=1.2,
        budget_probe_recover_cost=0.6,
        budget_probe_recovery_ratio=0.8,
        budget_probe_cooldown_s=0.2,
        budget_probe_action="force_hold",
        budget_probe_min_success_rate=0.95,
        budget_probe_max_avg_recovery_s=5.0,
    )


def test_extract_hints_from_matrix_contains_expected_actions():
    module = _load_module()
    matrix = {
        "results": [
            {
                "channel": "ths_ipc",
                "gate_ok": False,
                "preflight": {"reason": "ths_ipc bridge unavailable: timed out"},
            },
            {
                "channel": "qmt",
                "gate_ok": False,
                "preflight": {"reason": "missing QMT_ACCOUNT_ID/QMT_ACCOUNT"},
            },
        ],
        "stability_probe": {
            "gate_ok": False,
            "status": "BLOCK",
            "tuning": {"suggested_env": {"DATA_PROVIDER_RETRY_COUNT": "2"}},
            "gate": {"failed_rules": [{"rule": "retry_rate", "detail": "too high"}]},
        },
        "budget_recovery_probe": {
            "gate_ok": False,
            "status": "BLOCK",
            "summary": {"recovery_success_rate": 0.8, "avg_recovery_duration_s": 6.2},
            "gate": {"failed_rules": [{"rule": "recovery_success_rate", "detail": "too low"}]},
        },
    }

    hints = module._extract_hints_from_matrix(matrix)
    text = "\n".join(hints)
    assert "THS IPC bridge" in text
    assert "QMT_ACCOUNT_ID" in text
    assert "DATA_PROVIDER_RETRY_COUNT=2" in text
    assert "retry_rate" in text
    assert "success_rate" in text
    assert "recovery_success_rate" in text


def test_build_strict_gate_cmd_respects_no_stability_probe():
    module = _load_module()
    args = _build_args(no_stability_probe=True, no_budget_recovery_probe=True)

    cmd = module._build_strict_gate_cmd(args, module.PROJECT_ROOT / "data" / "smoke" / "reports" / "x.json")
    text = " ".join(cmd)
    assert "--include-order-probe" in text
    assert "--no-reconcile" in text
    assert "--no-stability-probe" in text
    assert "--no-budget-recovery-probe" in text
    assert "--probe-iterations" not in text
    assert "--with-budget-recovery-probe" not in text


def test_build_strict_gate_cmd_contains_budget_probe_flags():
    module = _load_module()
    args = _build_args(no_stability_probe=False, no_budget_recovery_probe=False)

    cmd = module._build_strict_gate_cmd(args, module.PROJECT_ROOT / "data" / "smoke" / "reports" / "x.json")
    text = " ".join(cmd)
    assert "--with-budget-recovery-probe" in text
    assert "--budget-probe-cycles 7" in text
    assert "--budget-probe-min-success-rate 0.95" in text


def test_build_check_only_cmd_appends_check_only_flag():
    module = _load_module()
    args = _build_args(no_stability_probe=True, no_budget_recovery_probe=True)
    args.include_order_probe = False
    args.no_reconcile = False

    cmd = module._build_check_only_cmd(args, module.PROJECT_ROOT / "data" / "smoke" / "reports" / "x.json")
    assert cmd[-1] == "--check-only"


def test_load_env_file_does_not_override_existing_value(monkeypatch):
    module = _load_module()
    temp_dir = Path(__file__).resolve().parents[2] / "_pytest_tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    env_path = temp_dir / "test_run_oneclick_gate.env"
    env_path.write_text("A=1\nB=2\n", encoding="utf-8")
    monkeypatch.setenv("B", "already")

    exists, loaded = module._load_env_file(env_path)
    assert exists is True
    assert "A" in loaded
    assert "B" not in loaded
    env_path.unlink(missing_ok=True)
