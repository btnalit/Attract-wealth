from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_module():
    root = Path(__file__).resolve().parents[2]
    module_path = root / "scripts" / "closure" / "run_p1_p4_closure.py"
    spec = importlib.util.spec_from_file_location("run_p1_p4_closure", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Proc:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _value_after_flag(cmd: list[str], flag: str) -> str:
    idx = cmd.index(flag)
    return str(cmd[idx + 1])


def test_run_p1_p4_closure_all_pass(monkeypatch):
    module = _load_module()
    temp_dir = module.PROJECT_ROOT / "_pytest_tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    closure_output = temp_dir / "p1_p4_closure_pass.json"
    closure_output.unlink(missing_ok=True)

    def _fake_run(cmd, cwd=None, capture_output=False, text=False, check=False):  # noqa: ARG001
        cmd = list(cmd)
        script = cmd[1]
        if script.endswith("run_sealoff_gate.py"):
            Path(_value_after_flag(cmd, "--matrix-output")).write_text("{}", encoding="utf-8")
            Path(_value_after_flag(cmd, "--oneclick-report-output")).write_text("{}", encoding="utf-8")
            Path(_value_after_flag(cmd, "--sealoff-report-output")).write_text(
                json.dumps({"gate_summary": {"all_passed": True}}, ensure_ascii=False),
                encoding="utf-8",
            )
            return _Proc(0, "p1 ok", "")
        if script.endswith("apply_runtime_profile.py"):
            Path(_value_after_flag(cmd, "--probe-output")).write_text(
                json.dumps({"gate": {"status": "PASS"}}, ensure_ascii=False),
                encoding="utf-8",
            )
            Path(_value_after_flag(cmd, "--output")).write_text(
                json.dumps({"stability_probe": {"returncode": 0}}, ensure_ascii=False),
                encoding="utf-8",
            )
            return _Proc(0, "p2 ok", "")
        if script.endswith("validate_evidence_schema.py"):
            Path(_value_after_flag(cmd, "--output")).write_text(
                json.dumps({"gate": {"status": "PASS"}}, ensure_ascii=False),
                encoding="utf-8",
            )
            return _Proc(0, "p3 ok", "")
        if script.endswith("p4_lifecycle_smoke.py"):
            Path(_value_after_flag(cmd, "--output")).write_text(
                json.dumps({"status": "PASS"}, ensure_ascii=False),
                encoding="utf-8",
            )
            return _Proc(0, "p4 ok", "")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(module.subprocess, "run", _fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_p1_p4_closure.py",
            "--output",
            str(closure_output),
            "--output-dir",
            str(temp_dir / "closure_pass"),
        ],
    )
    rc = module.main()
    assert rc == 0
    payload = json.loads(closure_output.read_text(encoding="utf-8"))
    assert payload["overall_status"] == "PASS"
    assert payload["counts"]["pass"] == 4
    assert payload["counts"]["block"] == 0


def test_run_p1_p4_closure_fail_fast(monkeypatch):
    module = _load_module()
    temp_dir = module.PROJECT_ROOT / "_pytest_tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    closure_output = temp_dir / "p1_p4_closure_fail_fast.json"
    closure_output.unlink(missing_ok=True)

    def _fake_run(cmd, cwd=None, capture_output=False, text=False, check=False):  # noqa: ARG001
        cmd = list(cmd)
        script = cmd[1]
        if script.endswith("run_sealoff_gate.py"):
            Path(_value_after_flag(cmd, "--sealoff-report-output")).write_text(
                json.dumps({"gate_summary": {"all_passed": True}}, ensure_ascii=False),
                encoding="utf-8",
            )
            Path(_value_after_flag(cmd, "--matrix-output")).write_text("{}", encoding="utf-8")
            Path(_value_after_flag(cmd, "--oneclick-report-output")).write_text("{}", encoding="utf-8")
            return _Proc(0, "p1 ok", "")
        if script.endswith("apply_runtime_profile.py"):
            Path(_value_after_flag(cmd, "--output")).write_text(
                json.dumps({"stability_probe": {"returncode": 0}}, ensure_ascii=False),
                encoding="utf-8",
            )
            Path(_value_after_flag(cmd, "--probe-output")).write_text("{}", encoding="utf-8")
            return _Proc(0, "p2 ok", "")
        if script.endswith("validate_evidence_schema.py"):
            Path(_value_after_flag(cmd, "--output")).write_text(
                json.dumps({"gate": {"status": "BLOCK"}}, ensure_ascii=False),
                encoding="utf-8",
            )
            return _Proc(1, "p3 block", "")
        if script.endswith("p4_lifecycle_smoke.py"):
            raise AssertionError("p4 should be skipped under fail-fast")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(module.subprocess, "run", _fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_p1_p4_closure.py",
            "--output",
            str(closure_output),
            "--output-dir",
            str(temp_dir / "closure_fail_fast"),
            "--fail-fast",
        ],
    )
    rc = module.main()
    assert rc == 1
    payload = json.loads(closure_output.read_text(encoding="utf-8"))
    assert payload["overall_status"] == "BLOCK"
    assert payload["counts"]["block"] == 1
    assert payload["counts"]["skip"] == 1


def test_run_p1_p4_closure_strict_mode_blocks_warn(monkeypatch):
    module = _load_module()
    temp_dir = module.PROJECT_ROOT / "_pytest_tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    closure_output = temp_dir / "p1_p4_closure_strict_warn_block.json"
    closure_output.unlink(missing_ok=True)

    captured_p1_cmd: list[str] = []
    captured_p3_cmd: list[str] = []

    def _fake_run(cmd, cwd=None, capture_output=False, text=False, check=False):  # noqa: ARG001
        cmd = list(cmd)
        script = cmd[1]
        if script.endswith("run_sealoff_gate.py"):
            captured_p1_cmd[:] = cmd
            Path(_value_after_flag(cmd, "--matrix-output")).write_text("{}", encoding="utf-8")
            Path(_value_after_flag(cmd, "--oneclick-report-output")).write_text("{}", encoding="utf-8")
            Path(_value_after_flag(cmd, "--sealoff-report-output")).write_text(
                json.dumps({"gate_summary": {"all_passed": True}}, ensure_ascii=False),
                encoding="utf-8",
            )
            return _Proc(0, "p1 pass", "")
        if script.endswith("apply_runtime_profile.py"):
            Path(_value_after_flag(cmd, "--probe-output")).write_text(
                json.dumps({"gate": {"status": "PASS"}}, ensure_ascii=False),
                encoding="utf-8",
            )
            Path(_value_after_flag(cmd, "--output")).write_text(
                json.dumps({"stability_probe": {"returncode": 0}}, ensure_ascii=False),
                encoding="utf-8",
            )
            return _Proc(0, "p2 ok", "")
        if script.endswith("validate_evidence_schema.py"):
            captured_p3_cmd[:] = cmd
            Path(_value_after_flag(cmd, "--output")).write_text(
                json.dumps({"gate": {"status": "WARN"}}, ensure_ascii=False),
                encoding="utf-8",
            )
            return _Proc(0, "p3 warn", "")
        if script.endswith("p4_lifecycle_smoke.py"):
            Path(_value_after_flag(cmd, "--output")).write_text(
                json.dumps({"status": "PASS"}, ensure_ascii=False),
                encoding="utf-8",
            )
            return _Proc(0, "p4 ok", "")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(module.subprocess, "run", _fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_p1_p4_closure.py",
            "--output",
            str(closure_output),
            "--output-dir",
            str(temp_dir / "closure_strict"),
            "--strict-mode",
            "--strict-level",
            "ci",
        ],
    )
    rc = module.main()
    assert rc == 1
    payload = json.loads(closure_output.read_text(encoding="utf-8"))
    assert payload["overall_status"] == "BLOCK"
    assert payload["params"]["strict_mode"] is True
    assert payload["params"]["strict_level"] == "ci"
    assert "--profile" in captured_p1_cmd
    assert "simulation_strict" in captured_p1_cmd
    assert "--seed-sample-evidence" in captured_p3_cmd
