from __future__ import annotations

import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_PAGES_DIR = PROJECT_ROOT / "src" / "frontend" / "src" / "pages"
FRONTEND_API_FILE = PROJECT_ROOT / "src" / "frontend" / "src" / "services" / "api.ts"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_frontend_pages_no_direct_fetch_calls() -> None:
    offenders: list[str] = []
    for file_path in FRONTEND_PAGES_DIR.rglob("*.tsx"):
        content = _read_text(file_path)
        if "fetch(" in content:
            offenders.append(str(file_path.relative_to(PROJECT_ROOT)))

    assert offenders == [], f"页面层仍存在直连 fetch: {offenders}"


def test_frontend_pages_no_api_base_env_access() -> None:
    offenders: list[str] = []
    for file_path in FRONTEND_PAGES_DIR.rglob("*.tsx"):
        content = _read_text(file_path)
        if "VITE_API_BASE_URL" in content:
            offenders.append(str(file_path.relative_to(PROJECT_ROOT)))

    assert offenders == [], f"页面层仍存在 API_BASE 直连: {offenders}"


def test_api_layer_public_exports_have_jsdoc() -> None:
    content = _read_text(FRONTEND_API_FILE)

    required_exports = [
        "export class ApiClientError",
        "export function apiUrl",
        "export async function apiRequest",
        "export const api =",
        "export const monitorApi =",
        "export const strategyApi =",
        "export const tradingApi =",
        "export const systemApi =",
    ]

    for export_token in required_exports:
        pattern = re.compile(rf"/\*\*[\s\S]*?\*/\s*{re.escape(export_token)}")
        assert pattern.search(content), f"缺少 JSDoc: {export_token}"


def test_api_layer_domain_methods_have_jsdoc() -> None:
    content = _read_text(FRONTEND_API_FILE)

    required_methods = [
        "getRisk",
        "getAuditLogs",
        "toggleRiskSwitch",
        "getStatus",
        "getQuote",
        "getDataHealth",
        "getVersions",
        "getHistory",
        "getBacktests",
        "getBacktestById",
        "runBacktest",
        "getVersionDiff",
        "getKnowledge",
        "getSnapshot",
        "getActiveOrders",
        "syncOrders",
        "switchChannel",
        "cancelAllOrders",
        "getConfig",
        "updateConfig",
        "getLlmConfig",
        "updateLlmConfig",
        "getRuntime",
        "getDataflowProviders",
        "switchDataflowProvider",
        "testWechatNotification",
    ]

    for method_name in required_methods:
        pattern = re.compile(rf"/\*\*[\s\S]*?\*/\s*{re.escape(method_name)}\s*:")
        assert pattern.search(content), f"缺少 JSDoc: {method_name}"
