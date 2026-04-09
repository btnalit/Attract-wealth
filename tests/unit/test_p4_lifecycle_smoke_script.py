from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_module():
    root = Path(__file__).resolve().parents[2]
    module_path = root / "scripts" / "strategy" / "p4_lifecycle_smoke.py"
    spec = importlib.util.spec_from_file_location("p4_lifecycle_smoke", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_p4_lifecycle_smoke_pass(monkeypatch):
    module = _load_module()
    temp_dir = module.ROOT_DIR / "_pytest_tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    data_dir = temp_dir / "p4_smoke_data_pass"
    output = temp_dir / "p4_lifecycle_smoke_pass.json"
    output.unlink(missing_ok=True)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "p4_lifecycle_smoke.py",
            "--data-dir",
            str(data_dir),
            "--output",
            str(output),
            "--bars",
            "48",
            "--max-combinations",
            "4",
            "--grid-json",
            "{\"lookback\":[2,4],\"position_ratio\":[0.4,0.8]}",
            "--top-k",
            "2",
        ],
    )
    rc = module.main()
    assert rc == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS"
    assert payload["result"]["strategy"]["status"] == "active"
    assert payload["result"]["grid"]["total_runs"] == 4
    assert len(payload["result"]["grid"]["top_results"]) == 2


def test_p4_lifecycle_smoke_blocks_on_invalid_grid(monkeypatch):
    module = _load_module()
    temp_dir = module.ROOT_DIR / "_pytest_tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    data_dir = temp_dir / "p4_smoke_data_block"
    output = temp_dir / "p4_lifecycle_smoke_block.json"
    output.unlink(missing_ok=True)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "p4_lifecycle_smoke.py",
            "--data-dir",
            str(data_dir),
            "--output",
            str(output),
            "--max-combinations",
            "2",
            "--grid-json",
            "{\"lookback\":[2,3,4],\"position_ratio\":[0.4,0.8]}",
        ],
    )
    rc = module.main()
    assert rc == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "BLOCK"
