from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_module():
    root = Path(__file__).resolve().parents[2]
    module_path = root / "scripts" / "dataflow" / "run_stability_baseline.py"
    spec = importlib.util.spec_from_file_location("run_stability_baseline", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


def test_main_writes_report_and_returns_zero(monkeypatch):
    module = _load_module()
    tmp_dir = module.ROOT_DIR / "_pytest_tmp" / "stability_baseline_1"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(module, "ROOT_DIR", tmp_dir)

    def _fake_run_profile(args, profile, report_dir):  # noqa: ARG001
        return {
            "profile": profile,
            "status": "PASS",
            "returncode": 0,
            "probe_summary": {"retry_rate": 0.1, "rate_limited_rate": 0.05},
        }

    monkeypatch.setattr(module, "_run_profile", _fake_run_profile)

    output = tmp_dir / "data" / "stability" / "baseline_report.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_stability_baseline.py",
            "--profiles",
            "dev_default,sim_default",
            "--output",
            str(output),
        ],
    )

    rc = module.main()
    assert rc == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["all_passed"] is True
    assert payload["counts"]["pass"] == 2
    latest = tmp_dir / "data" / "stability" / "stability_baseline_latest.json"
    assert latest.exists()


def test_main_returns_nonzero_when_any_profile_fails(monkeypatch):
    module = _load_module()
    tmp_dir = module.ROOT_DIR / "_pytest_tmp" / "stability_baseline_2"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(module, "ROOT_DIR", tmp_dir)

    statuses = {"dev_default": "PASS", "prod_live": "FAIL"}

    def _fake_run_profile(args, profile, report_dir):  # noqa: ARG001
        status = statuses[profile]
        return {
            "profile": profile,
            "status": status,
            "returncode": 0 if status == "PASS" else 1,
            "probe_summary": {"retry_rate": 0.2, "rate_limited_rate": 0.1},
        }

    monkeypatch.setattr(module, "_run_profile", _fake_run_profile)

    output = tmp_dir / "data" / "stability" / "baseline_report_fail.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_stability_baseline.py",
            "--profiles",
            "dev_default,prod_live",
            "--output",
            str(output),
        ],
    )

    rc = module.main()
    assert rc == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["all_passed"] is False
    assert payload["counts"]["fail"] == 1


def test_parse_args_defaults_probe_failure_every_is_9(monkeypatch):
    module = _load_module()
    monkeypatch.setattr(sys, "argv", ["run_stability_baseline.py"])
    args = module._parse_args()
    assert args.probe_failure_every == 9
