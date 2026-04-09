from __future__ import annotations

import src.core.startup_preflight as startup_preflight_module
from src.core.startup_preflight import run_startup_preflight


def _find_check(report: dict, name: str) -> dict:
    for item in report.get("checks", []):
        if item.get("name") == name:
            return item
    return {}


def test_simulation_preflight_ok(monkeypatch):
    monkeypatch.setenv("TRADING_CHANNEL", "simulation")
    report = run_startup_preflight(channel="simulation")
    assert report["channel"] == "simulation"
    assert report["ok"] is True
    assert _find_check(report, "trading_channel_supported")["ok"] is True


def test_qmt_preflight_reports_missing_required_fields(monkeypatch):
    monkeypatch.setenv("TRADING_CHANNEL", "qmt")
    monkeypatch.delenv("QMT_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("QMT_ACCOUNT", raising=False)
    monkeypatch.delenv("QMT_PATH", raising=False)

    report = run_startup_preflight(channel="qmt")
    assert report["ok"] is False
    assert _find_check(report, "qmt_account")["ok"] is False
    assert _find_check(report, "qmt_path")["ok"] is False


def test_ths_auto_stub_policy(monkeypatch):
    monkeypatch.delenv("THS_AUTO_ALLOW_STUB", raising=False)
    report = run_startup_preflight(channel="ths_auto")
    assert report["ok"] is False
    assert _find_check(report, "ths_auto_stub_policy")["ok"] is False

    monkeypatch.setenv("THS_AUTO_ALLOW_STUB", "true")
    report_allowed = run_startup_preflight(channel="ths_auto")
    assert _find_check(report_allowed, "ths_auto_stub_policy")["ok"] is True


def test_stability_probe_checks_pandas_availability_flag(monkeypatch):
    monkeypatch.setenv("TRADING_CHANNEL", "simulation")

    def _raise_import_error(name: str):
        raise ImportError(name)

    monkeypatch.setattr(startup_preflight_module.importlib, "import_module", _raise_import_error)
    report_no_pandas = run_startup_preflight(channel="simulation", include_stability_probe=True)
    pandas_check = _find_check(report_no_pandas, "pandas_module")
    assert pandas_check["ok"] is False
    assert pandas_check["severity"] == "warning"

    monkeypatch.setattr(startup_preflight_module.importlib, "import_module", lambda _: object())
    report_with_pandas = run_startup_preflight(channel="simulation", include_stability_probe=True)
    assert _find_check(report_with_pandas, "pandas_module")["ok"] is True


def test_ths_ipc_runtime_check_blocks_mock_runtime(monkeypatch):
    monkeypatch.setenv("TRADING_CHANNEL", "ths_ipc")
    monkeypatch.delenv("THS_IPC_ALLOW_MOCK", raising=False)
    monkeypatch.delenv("THS_IPC_REQUIRE_RUNTIME", raising=False)
    monkeypatch.setattr(startup_preflight_module, "_port_reachable", lambda *_args, **_kwargs: (True, ""))
    monkeypatch.setattr(
        startup_preflight_module,
        "_probe_ths_ipc_runtime",
        lambda *_args, **_kwargs: (False, {"in_ths_api": False, "in_xiadan_api": False}, ""),
    )

    report = run_startup_preflight(channel="ths_ipc")
    assert report["ok"] is False
    runtime_check = _find_check(report, "ths_ipc_runtime")
    assert runtime_check["ok"] is False
    assert runtime_check["severity"] == "critical"


def test_ths_ipc_runtime_check_can_be_relaxed_by_allow_mock(monkeypatch):
    monkeypatch.setenv("TRADING_CHANNEL", "ths_ipc")
    monkeypatch.setenv("THS_IPC_ALLOW_MOCK", "true")
    monkeypatch.setattr(startup_preflight_module, "_port_reachable", lambda *_args, **_kwargs: (True, ""))
    monkeypatch.setattr(
        startup_preflight_module,
        "_probe_ths_ipc_runtime",
        lambda *_args, **_kwargs: (False, {"in_ths_api": False, "in_xiadan_api": False}, ""),
    )

    report = run_startup_preflight(channel="ths_ipc")
    assert report["ok"] is True
    assert _find_check(report, "ths_ipc_runtime") == {}


def test_ths_ipc_preflight_adds_easytrader_diag_on_bridge_failure(monkeypatch):
    monkeypatch.setenv("TRADING_CHANNEL", "ths_ipc")
    monkeypatch.setenv("THS_IPC_ENABLE_EASYTRADER_DIAG", "true")
    monkeypatch.setattr(startup_preflight_module, "_port_reachable", lambda *_args, **_kwargs: (False, "unreachable"))
    monkeypatch.setattr(
        startup_preflight_module,
        "probe_easytrader_readiness",
        lambda **_kwargs: {"ok": True, "summary": {"positions_count": 1}, "errors": [], "meta": {"reason": "connected"}},
    )

    report = run_startup_preflight(channel="ths_ipc")
    diag_check = _find_check(report, "ths_easytrader_diag")
    assert diag_check["ok"] is True
    assert diag_check["severity"] == "warning"


def test_ths_auto_preflight_can_pass_with_easytrader_runtime(monkeypatch):
    monkeypatch.setenv("THS_EXE_PATH", __file__)
    monkeypatch.delenv("THS_AUTO_ALLOW_STUB", raising=False)
    monkeypatch.setattr(
        startup_preflight_module,
        "probe_easytrader_readiness",
        lambda **_kwargs: {
            "ok": True,
            "summary": {"has_balance": True, "positions_count": 1},
            "errors": [],
            "meta": {"reason": "connected"},
        },
    )

    report = run_startup_preflight(channel="ths_auto")
    assert _find_check(report, "ths_auto_easytrader")["ok"] is True
    assert _find_check(report, "ths_auto_stub_policy")["ok"] is True
