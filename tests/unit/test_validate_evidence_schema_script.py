from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_module():
    root = Path(__file__).resolve().parents[2]
    module_path = root / "scripts" / "evidence" / "validate_evidence_schema.py"
    spec = importlib.util.spec_from_file_location("validate_evidence_schema", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _full_record() -> dict:
    return {
        "id": "ev-1",
        "timestamp": 1.0,
        "phase": "execute",
        "session_id": "sess-1",
        "request_id": "req-1",
        "trace_id": "trace-1",
        "ticker": "000001",
        "channel": "simulation",
        "decision": "BUY",
        "action": "BUY",
        "payload": {
            "evidence_version": "2026.04.08.1",
            "phase": "execute",
            "timestamp": 1.0,
            "session_id": "sess-1",
            "request_id": "req-1",
            "ticker": "000001",
            "channel": "simulation",
            "decision": "BUY",
            "action": "BUY",
            "risk_check": {"passed": True},
            "trace": {
                "trace_id": "trace-1",
                "request_id": "req-1",
                "session_id": "sess-1",
                "phase": "execute",
                "channel": "simulation",
                "ticker": "000001",
            },
            "degrade_policy": {"enabled": True},
            "budget_recovery_guard": {"active": False},
            "reconciliation_guard": {"blocked": False, "ok_streak": 0},
            "context_digest": {"portfolio": {}},
            "llm_runtime": {"enabled": True},
            "analysis_reports": {"technical": {"summary": "ok"}},
            "degrade_flags": [],
        },
    }


def test_validate_evidence_schema_pass(monkeypatch):
    module = _load_module()
    temp_dir = module.ROOT_DIR / "_pytest_tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    output = temp_dir / "evidence_schema_pass.json"
    output.unlink(missing_ok=True)

    monkeypatch.setattr(module.TradingLedger, "list_decision_evidence", staticmethod(lambda **kwargs: [_full_record()]))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "validate_evidence_schema.py",
            "--output",
            str(output),
            "--min-completeness-rate",
            "0.9",
            "--max-inconsistent-rate",
            "0.1",
        ],
    )
    rc = module.main()
    assert rc == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["gate"]["status"] == "PASS"
    assert payload["summary"]["counts"]["complete"] == 1


def test_validate_evidence_schema_block_on_missing_fields(monkeypatch):
    module = _load_module()
    temp_dir = module.ROOT_DIR / "_pytest_tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    output = temp_dir / "evidence_schema_block.json"
    output.unlink(missing_ok=True)

    row = _full_record()
    row["payload"].pop("trace")
    monkeypatch.setattr(module.TradingLedger, "list_decision_evidence", staticmethod(lambda **kwargs: [row]))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "validate_evidence_schema.py",
            "--output",
            str(output),
            "--min-completeness-rate",
            "1.0",
        ],
    )
    rc = module.main()
    assert rc == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["gate"]["status"] == "BLOCK"
    assert any(item["rule"] == "completeness_rate" for item in payload["gate"]["failed_rules"])


def test_validate_evidence_schema_seed_sample_rows(monkeypatch):
    module = _load_module()
    temp_dir = module.ROOT_DIR / "_pytest_tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    output = temp_dir / "evidence_schema_seed.json"
    output.unlink(missing_ok=True)

    seed_counter = {"n": 0}

    def _fake_record(payload):
        seed_counter["n"] += 1
        return f"seed-{seed_counter['n']}"

    def _fake_list(**kwargs):
        request_id = kwargs.get("request_id", "")
        row = _full_record()
        row["request_id"] = request_id
        row["session_id"] = f"{request_id}-sess"
        row["trace_id"] = f"{request_id}-trace-001"
        row["payload"]["request_id"] = request_id
        row["payload"]["session_id"] = f"{request_id}-sess"
        row["payload"]["trace"]["request_id"] = request_id
        row["payload"]["trace"]["session_id"] = f"{request_id}-sess"
        row["payload"]["trace"]["trace_id"] = f"{request_id}-trace-001"
        return [row]

    monkeypatch.setattr(module.TradingLedger, "record_decision_evidence", staticmethod(_fake_record))
    monkeypatch.setattr(module.TradingLedger, "list_decision_evidence", staticmethod(_fake_list))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "validate_evidence_schema.py",
            "--output",
            str(output),
            "--seed-sample-evidence",
            "--sample-count",
            "4",
            "--disallow-empty",
        ],
    )
    rc = module.main()
    assert rc == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["gate"]["status"] == "PASS"
    assert payload["seed"]["enabled"] is True
    assert len(payload["seed"]["seeded_ids"]) == 4
