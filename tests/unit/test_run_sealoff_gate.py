from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path


def _load_module():
    root = Path(__file__).resolve().parents[2]
    module_path = root / "scripts" / "smoke" / "run_sealoff_gate.py"
    spec = importlib.util.spec_from_file_location("run_sealoff_gate", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_apply_p2b3_baseline_env_sets_expected_values(monkeypatch):
    module = _load_module()
    monkeypatch.delenv("DATA_PROVIDER_MAX_WAIT_MS", raising=False)
    monkeypatch.delenv("DATA_QUALITY_ERROR_BLOCK", raising=False)

    applied = module._apply_p2b3_baseline_env()
    assert applied["DATA_PROVIDER_MAX_WAIT_MS"] == "400"
    assert applied["DATA_QUALITY_ERROR_BLOCK"] == "0.40"
    assert os.environ["DATA_PROVIDER_MAX_WAIT_MS"] == "400"
    assert os.environ["DATA_QUALITY_ERROR_BLOCK"] == "0.40"


def test_build_oneclick_cmd_for_dual_channel_profile_contains_expected_flags():
    module = _load_module()
    profile = module.PROFILES["dual_channel_strict"]
    args = argparse.Namespace(
        env_file=".env",
        no_load_env_file=False,
        no_auto_start_ths_bridge=False,
        keep_bridge=False,
        no_precheck_first=False,
        no_fail_fast_precheck=False,
        python_executable="",
    )
    matrix_output = module.PROJECT_ROOT / "data" / "smoke" / "reports" / "matrix_test.json"
    oneclick_output = module.PROJECT_ROOT / "data" / "smoke" / "reports" / "oneclick_test.json"
    cmd = module._build_oneclick_cmd(args, profile, matrix_output, oneclick_output)
    text = " ".join(cmd)

    assert "--channels ths_ipc,qmt" in text
    assert "--include-order-probe" not in text
    assert "--force-live-order" not in text
    assert "--no-reconcile" not in text
    assert "--no-stability-probe" not in text
    assert "--no-budget-recovery-probe" not in text
    assert "--budget-probe-cycles" in text
    assert "--probe-iterations" in text
    assert "--probe-fail-on-quality critical" in text


def test_build_oneclick_cmd_for_ths_sim_strict_profile_contains_expected_channels():
    module = _load_module()
    profile = module.PROFILES["ths_sim_strict"]
    args = argparse.Namespace(
        env_file=".env",
        no_load_env_file=False,
        no_auto_start_ths_bridge=False,
        keep_bridge=False,
        no_precheck_first=False,
        no_fail_fast_precheck=False,
        python_executable="",
    )
    matrix_output = module.PROJECT_ROOT / "data" / "smoke" / "reports" / "matrix_test.json"
    oneclick_output = module.PROJECT_ROOT / "data" / "smoke" / "reports" / "oneclick_test.json"
    cmd = module._build_oneclick_cmd(args, profile, matrix_output, oneclick_output)
    text = " ".join(cmd)

    assert "--channels ths_ipc,simulation" in text
    assert "--include-order-probe" not in text
    assert "--force-live-order" not in text
    assert "--no-reconcile" not in text
    assert "--no-stability-probe" not in text
    assert "--no-budget-recovery-probe" not in text
    assert "--budget-probe-min-success-rate" in text


def test_main_rejects_live_order_profile_without_explicit_allow(monkeypatch):
    module = _load_module()
    monkeypatch.setattr(sys, "argv", ["run_sealoff_gate.py", "--profile", "ths_real_probe", "--dry-run"])
    assert module.main() == 2


def test_main_dry_run_writes_sealoff_report(monkeypatch):
    module = _load_module()
    root = module.PROJECT_ROOT
    temp_dir = root / "_pytest_tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    matrix_path = temp_dir / "matrix_sealoff_test.json"
    oneclick_path = temp_dir / "oneclick_sealoff_test.json"
    sealoff_path = temp_dir / "sealoff_test.json"
    for path in (matrix_path, oneclick_path, sealoff_path):
        path.unlink(missing_ok=True)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_sealoff_gate.py",
            "--profile",
            "dual_channel_strict",
            "--dry-run",
            "--matrix-output",
            str(matrix_path),
            "--oneclick-report-output",
            str(oneclick_path),
            "--sealoff-report-output",
            str(sealoff_path),
        ],
    )

    rc = module.main()
    assert rc == 0
    assert sealoff_path.exists()

    report = json.loads(sealoff_path.read_text(encoding="utf-8"))
    assert report["dry_run"] is True
    assert report["profile"]["name"] == "dual_channel_strict"
    assert report["profile"]["with_budget_recovery_probe"] is True
    assert report["paths"]["matrix_report"] == str(matrix_path)
    assert report["paths"]["oneclick_report"] == str(oneclick_path)
