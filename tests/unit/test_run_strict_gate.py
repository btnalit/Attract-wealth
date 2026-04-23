from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


def _load_module():
    root = Path(__file__).resolve().parents[2]
    module_path = root / "scripts" / "smoke" / "run_strict_gate.py"
    spec = importlib.util.spec_from_file_location("run_strict_gate", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_extract_failure_hints_contains_expected_actions():
    module = _load_module()
    report = {
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
            "tuning": {
                "suggested_env": {
                    "DATA_PROVIDER_MAX_WAIT_MS": "800",
                }
            },
            "gate": {
                "failed_rules": [
                    {"rule": "retry_rate", "detail": "retry_rate too high"},
                ]
            },
        },
        "budget_recovery_probe": {
            "gate_ok": False,
            "status": "BLOCK",
            "summary": {"recovery_success_rate": 0.8, "avg_recovery_duration_s": 6.2},
            "gate": {
                "failed_rules": [
                    {"rule": "recovery_success_rate", "detail": "too low"},
                ]
            },
        },
    }

    hints = module.extract_failure_hints(report)
    text = "\n".join(hints)
    assert "THS IPC bridge 未就绪" in text
    assert "QMT 账户未配置" in text
    assert "DATA_PROVIDER_MAX_WAIT_MS=800" in text
    assert "retry_rate" in text
    assert "success_rate" in text
    assert "recovery_success_rate" in text


def test_build_matrix_command_contains_budget_probe_flags():
    module = _load_module()
    args = type(
        "Args",
        (),
        {
            "output": "data/smoke/reports/matrix_strict_latest.json",
            "channels": "ths_ipc,simulation",
            "no_reconcile": False,
            "include_order_probe": False,
            "force_live_order": False,
            "with_stability_probe": False,
            "probe_iterations": 80,
            "probe_failure_every": 9,
            "probe_rate_limit_per_minute": 90,
            "probe_max_wait_ms": 0,
            "probe_retry_count": 2,
            "probe_retry_base_ms": 30,
            "probe_fail_on_quality": "critical",
            "with_budget_recovery_probe": True,
            "budget_probe_cycles": 5,
            "budget_probe_active_steps": 1,
            "budget_probe_recovery_steps": 2,
            "budget_probe_interval_ms": 0,
            "budget_probe_budget_usd": 1.0,
            "budget_probe_exceed_cost": 1.2,
            "budget_probe_recover_cost": 0.6,
            "budget_probe_recovery_ratio": 0.8,
            "budget_probe_cooldown_s": 0.1,
            "budget_probe_action": "force_hold",
            "budget_probe_min_success_rate": 0.95,
            "budget_probe_max_avg_recovery_s": 5.0,
        },
    )()
    cmd = module.build_matrix_command(args)
    text = " ".join(cmd)
    assert "--with-budget-recovery-probe" in text
    assert "--budget-probe-cycles 5" in text
    assert "--budget-probe-min-success-rate 0.95" in text


def test_parse_args_defaults_probe_failure_every_is_9(monkeypatch):
    module = _load_module()
    monkeypatch.setattr(sys, "argv", ["run_strict_gate.py"])
    args = module._parse_args()
    assert args.probe_failure_every == 9
