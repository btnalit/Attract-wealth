from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_PACKAGE_JSON = PROJECT_ROOT / "src" / "frontend" / "package.json"


def test_frontend_package_has_gate_scripts() -> None:
    payload = json.loads(FRONTEND_PACKAGE_JSON.read_text(encoding="utf-8"))
    scripts = payload.get("scripts", {})
    assert isinstance(scripts, dict)
    assert "lint" in scripts
    assert "build" in scripts
    assert "test" in scripts
