from __future__ import annotations

import asyncio

from src import main as main_module


def test_health_and_system_info_return_enveloped_payloads():
    health_payload = asyncio.run(main_module.health_check())
    assert health_payload["ok"] is True
    assert health_payload["code"] == "HEALTH_OK"
    assert health_payload["data"]["status"] == "ok"

    main_module.app.state.startup_preflight = {"ok": True, "summary": {"critical_failed": 0}}
    main_module.app.state.ths_bridge = {"ready": True}
    info_payload = asyncio.run(main_module.system_info())
    assert info_payload["ok"] is True
    assert info_payload["code"] == "SYSTEM_INFO_OK"
    assert "startup_preflight_ok" in info_payload["data"]
    assert "ths_bridge" in info_payload["data"]


def test_openapi_hides_legacy_llm_config_path():
    main_module.app.openapi_schema = None
    schema = main_module.app.openapi()
    paths = schema.get("paths", {})
    assert "/api/system/llm/config" in paths
    assert "/api/system/llm-config" not in paths

