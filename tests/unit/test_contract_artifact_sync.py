from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SYNC_SCRIPT = PROJECT_ROOT / "scripts" / "contracts" / "sync_openapi_types.py"


def _run_sync(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SYNC_SCRIPT), *args],
        cwd=str(cwd or PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


def test_sync_script_supports_roundtrip_check(tmp_path: Path) -> None:
    openapi_output = tmp_path / "openapi.json"
    types_output = tmp_path / "openapi-types.ts"
    sync_report = tmp_path / "sync-report.json"
    check_report = tmp_path / "check-report.json"

    sync_proc = _run_sync(
        [
            "--openapi-output",
            str(openapi_output),
            "--types-output",
            str(types_output),
            "--report-output",
            str(sync_report),
        ]
    )
    assert sync_proc.returncode == 0, sync_proc.stdout + "\n" + sync_proc.stderr
    assert openapi_output.exists()
    assert types_output.exists()

    sync_result = json.loads(sync_report.read_text(encoding="utf-8"))
    assert sync_result["ok"] is True
    assert sync_result["mode"] == "sync"
    assert sync_result["path_count"] > 0
    assert sync_result["method_count"] > 0
    assert sync_result["component_schema_count"] > 0
    assert sync_result["request_schema_ref_count"] > 0

    types_text = types_output.read_text(encoding="utf-8")
    assert "OPENAPI_PATH_METHODS" in types_text
    assert "OPENAPI_COMPONENT_SCHEMA_NAMES" in types_text
    assert "OpenApiComponentSchemaMap" in types_text
    assert "OPENAPI_REQUEST_BODY_SCHEMAS" in types_text
    assert "export type StrategyBacktestRequest" in types_text
    assert "/api/system/llm/config" in types_text
    assert "/api/system/llm-config" not in types_text

    check_proc = _run_sync(
        [
            "--check",
            "--openapi-output",
            str(openapi_output),
            "--types-output",
            str(types_output),
            "--report-output",
            str(check_report),
        ]
    )
    assert check_proc.returncode == 0, check_proc.stdout + "\n" + check_proc.stderr
    check_result = json.loads(check_report.read_text(encoding="utf-8"))
    assert check_result["ok"] is True
    assert all(check_result["checks"].values())


def test_default_contract_artifacts_in_repo_are_synced() -> None:
    check_proc = _run_sync(["--check"])
    assert check_proc.returncode == 0, check_proc.stdout + "\n" + check_proc.stderr
