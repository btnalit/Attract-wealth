from __future__ import annotations

from src.services import ths_diagnosis_service as module


def test_get_host_diagnosis_aggregates_core_snapshots(monkeypatch):
    monkeypatch.setattr(module, "is_xiadan_running", lambda: (True, ""))
    monkeypatch.setattr(
        module,
        "collect_xiadan_ui_context",
        lambda: {
            "running": True,
            "process_count": 1,
            "strategy_page_open": False,
            "window_titles": ["网上股票交易系统5.0"],
            "strategy_related_windows": [],
            "error": "",
        },
    )
    monkeypatch.setattr(
        module,
        "probe_bridge_runtime",
        lambda **kwargs: {  # noqa: ARG005
            "reachable": True,
            "runtime_ok": False,
            "runtime": {"in_ths_api": False, "in_xiadan_api": False},
            "error": "",
        },
    )
    monkeypatch.setattr(module, "collect_host_observability_snapshot", lambda *_args, **_kwargs: {"host_execution_evidence": False})
    monkeypatch.setattr(
        module,
        "analyze_host_trigger_chain",
        lambda *_args, **_kwargs: {  # noqa: ARG005
            "stage": "UI_TRIGGER_PAGE_NOT_OPEN",
            "status": "FAIL",
            "summary": "not open",
            "blockers": ["strategy trigger page not open"],
            "suggestions": ["在同花顺交易会话内手动打开一次“策略条件单/信号策略”并保持窗口可见。"],
            "facts": {"strategy_page_open": False},
        },
    )
    monkeypatch.setattr(module, "read_ths_account_context", lambda *_args, **_kwargs: {"mode_hint": "paper"})

    service = module.THSDiagnosisService()
    payload = service.get_host_diagnosis(host="127.0.0.1", port=8089, timeout_s=1.2)

    assert payload["status"] == "FAIL"
    assert payload["ready"] is False
    assert payload["runtime_probe"]["reachable"] is True
    assert payload["runtime_probe"]["runtime_ok"] is False
    assert payload["host_trigger_diagnosis"]["stage"] == "UI_TRIGGER_PAGE_NOT_OPEN"
    assert any("runtime 不是 THS 宿主" in hint for hint in payload["hints"])


def test_get_host_diagnosis_pass_status_when_trigger_ready(monkeypatch):
    monkeypatch.setattr(module, "is_xiadan_running", lambda: (True, ""))
    monkeypatch.setattr(module, "collect_xiadan_ui_context", lambda: {"running": True, "strategy_page_open": True, "window_titles": []})
    monkeypatch.setattr(
        module,
        "probe_bridge_runtime",
        lambda **kwargs: {  # noqa: ARG005
            "reachable": True,
            "runtime_ok": True,
            "runtime": {"in_ths_api": True, "in_xiadan_api": False},
            "error": "",
        },
    )
    monkeypatch.setattr(module, "collect_host_observability_snapshot", lambda *_args, **_kwargs: {"host_execution_evidence": True})
    monkeypatch.setattr(
        module,
        "analyze_host_trigger_chain",
        lambda *_args, **_kwargs: {  # noqa: ARG005
            "stage": "HOST_RUNTIME_READY",
            "status": "PASS",
            "summary": "ready",
            "blockers": [],
            "suggestions": ["可继续执行 A36/A35/A34 全量守门。"],
            "facts": {"runtime_ok": True},
        },
    )
    monkeypatch.setattr(module, "read_ths_account_context", lambda *_args, **_kwargs: {"mode_hint": "paper"})

    service = module.THSDiagnosisService()
    payload = service.get_host_diagnosis()

    assert payload["status"] == "PASS"
    assert payload["ready"] is True
    assert payload["runtime_probe"]["runtime_ok"] is True
    assert payload["host_trigger_diagnosis"]["stage"] == "HOST_RUNTIME_READY"

