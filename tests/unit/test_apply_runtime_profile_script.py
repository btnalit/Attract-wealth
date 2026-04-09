from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_module():
    root = Path(__file__).resolve().parents[2]
    module_path = root / "scripts" / "dataflow" / "apply_runtime_profile.py"
    spec = importlib.util.spec_from_file_location("apply_runtime_profile", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_probe_cmd_contains_expected_flags():
    module = _load_module()
    args = type(
        "Args",
        (),
        {
            "probe_iterations": 20,
            "probe_failure_every": 5,
            "probe_rate_limit_per_minute": 66,
            "probe_max_wait_ms": 123,
            "probe_retry_count": 3,
            "probe_retry_base_ms": 40,
            "probe_fail_on_quality": "warn",
        },
    )()
    output = module.ROOT_DIR / "data" / "stability" / "probe_test.json"
    cmd = module._build_probe_cmd(args, output)
    text = " ".join(cmd)
    assert "--iterations 20" in text
    assert "--rate-limit-per-minute 66" in text
    assert "--fail-on-quality warn" in text
    assert str(output) in text


def test_main_applies_profile_and_writes_report(monkeypatch):
    module = _load_module()
    temp_dir = module.ROOT_DIR / "_pytest_tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    output = temp_dir / "profile_apply_test.json"
    output.unlink(missing_ok=True)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "apply_runtime_profile.py",
            "--profile",
            "ths_paper_default",
            "--output",
            str(output),
        ],
    )
    rc = module.main()
    assert rc == 0
    assert output.exists()

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["profile"] == "ths_paper_default"
    assert payload["profile_version"]
    assert payload["applied_env"]["DATA_PROVIDER_RATE_LIMIT_PER_MINUTE"] == "120"
