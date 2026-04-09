from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_module():
    root = Path(__file__).resolve().parents[2]
    module_path = root / "scripts" / "ths" / "run_easytrader_setup_and_probe.py"
    spec = importlib.util.spec_from_file_location("run_easytrader_setup_and_probe", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_extract_key_info():
    module = _load_module()
    payload = {
        "probe": {
            "summary": {
                "available_cash": 1000,
                "total_assets": 2000,
                "market_value": 800,
                "positions_count": 2,
                "orders_count": 3,
                "trades_count": 4,
            },
            "account": {"account_id": "ACC01", "currency": "CNY"},
            "positions": [
                {"ticker": "000001", "market_value": 500, "quantity": 100},
                {"ticker": "000002", "market_value": 200, "quantity": 50},
            ],
        }
    }
    key_info = module._extract_key_info(payload)
    assert key_info["account_id"] == "ACC01"
    assert key_info["positions_count"] == 2
    assert key_info["orders_count"] == 3
    assert key_info["trades_count"] == 4
    assert key_info["top_positions"][0]["ticker"] == "000001"


def test_main_fails_when_python32_missing(monkeypatch):
    module = _load_module()
    output = Path(__file__).resolve().parents[2] / "_pytest_tmp" / "easytrader_setup_missing_py32.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)

    monkeypatch.setattr(module, "_resolve_python32", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(module, "inspect_easytrader_runtime", lambda **_kwargs: {"ok": False, "errors": []})

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_easytrader_setup_and_probe.py",
            "--output",
            str(output),
        ],
    )
    rc = module.main()
    assert rc == 2
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["ok"] is False
    assert any("32 位 Python" in hint for hint in payload.get("hints", []))
