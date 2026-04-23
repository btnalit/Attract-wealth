from __future__ import annotations

from src.core.ths_host_autostart import (
    analyze_host_trigger_chain,
    AUTOSTART_MARK_BEGIN,
    AUTOSTART_MARK_END,
    build_autostart_injection_block,
    collect_host_observability_snapshot,
    inject_autostart_block,
    read_ths_account_context,
    render_host_bootstrap_script,
    summarize_trade_snapshot,
)


def test_inject_autostart_block_after_anchor():
    source = "from ths_api import *\n\nvalue = 1\n"
    patched = inject_autostart_block(source)

    assert AUTOSTART_MARK_BEGIN in patched
    assert AUTOSTART_MARK_END in patched
    assert patched.find(AUTOSTART_MARK_BEGIN) > patched.find("from ths_api import *")


def test_inject_autostart_block_is_idempotent():
    source = "from ths_api import *\n\nvalue = 1\n"
    once = inject_autostart_block(source)
    twice = inject_autostart_block(once)

    assert once == twice
    assert once.count(AUTOSTART_MARK_BEGIN) == 1
    assert once.count(AUTOSTART_MARK_END) == 1


def test_build_injection_block_and_bootstrap_template_contains_expected_symbol():
    block = build_autostart_injection_block("\n")
    bootstrap = render_host_bootstrap_script()

    assert "ensure_laicai_bridge_autostart" in block
    assert "my_signals_exec.jsonl" in block
    assert "my_signals_error.log" in block
    assert "def ensure_laicai_bridge_autostart" in bootstrap
    assert "import laicai_bridge as _bridge" in bootstrap
    assert "bootstrap_exec.jsonl" in bootstrap
    assert "bootstrap_error.log" in bootstrap
    assert "def _persist_error" in bootstrap


def test_collect_host_observability_snapshot_reads_marker_and_error(tmp_path):
    obs_dir = tmp_path / "script" / "_laicai_obs"
    obs_dir.mkdir(parents=True, exist_ok=True)
    (obs_dir / "my_signals_exec.jsonl").write_text('{"stage":"my_signals_enter","ts":1}\n', encoding="utf-8")
    (obs_dir / "bootstrap_exec.jsonl").write_text('{"stage":"started","ts":2}\n', encoding="utf-8")
    (obs_dir / "bootstrap_error.log").write_text("trace line 1\ntrace line 2\n", encoding="utf-8")

    snapshot = collect_host_observability_snapshot(tmp_path)

    assert snapshot["host_execution_evidence"] is True
    assert snapshot["has_errors"] is True
    assert snapshot["my_signals"]["marker_exists"] is True
    assert snapshot["my_signals"]["last_marker"]["stage"] == "my_signals_enter"
    assert snapshot["bootstrap"]["marker_exists"] is True
    assert snapshot["bootstrap"]["last_marker"]["stage"] == "started"
    assert snapshot["bootstrap"]["error_exists"] is True
    assert snapshot["bootstrap"]["error_tail"][-1] == "trace line 2"


def test_analyze_host_trigger_chain_no_xiadan_process(tmp_path):
    snapshot = collect_host_observability_snapshot(tmp_path)
    diag = analyze_host_trigger_chain(
        snapshot,
        xiadan_running=False,
        runtime_probe={"reachable": False, "runtime_ok": False, "runtime": {}},
    )

    assert diag["stage"] == "NO_XIADAN_PROCESS"
    assert diag["status"] == "FAIL"
    assert "xiadan process not running" in diag["blockers"]


def test_analyze_host_trigger_chain_ui_trigger_page_not_open(tmp_path):
    snapshot = collect_host_observability_snapshot(tmp_path)
    diag = analyze_host_trigger_chain(
        snapshot,
        xiadan_running=True,
        runtime_probe={"reachable": False, "runtime_ok": False, "runtime": {}},
        ui_context={
            "running": True,
            "strategy_page_open": False,
            "window_titles": ["网上股票交易系统5.0"],
        },
    )

    assert diag["stage"] == "UI_TRIGGER_PAGE_NOT_OPEN"
    assert diag["status"] == "FAIL"
    assert "strategy trigger page not open" in diag["blockers"]
    assert diag["facts"]["strategy_page_open"] is False


def test_analyze_host_trigger_chain_mock_runtime_with_markers(tmp_path):
    obs_dir = tmp_path / "script" / "_laicai_obs"
    obs_dir.mkdir(parents=True, exist_ok=True)
    (obs_dir / "my_signals_exec.jsonl").write_text('{"stage":"my_signals_enter","ts":1}\n{"stage":"my_signals_exit","ts":2}\n', encoding="utf-8")
    (obs_dir / "bootstrap_exec.jsonl").write_text('{"stage":"thread_started","ts":3}\n', encoding="utf-8")

    snapshot = collect_host_observability_snapshot(tmp_path)
    diag = analyze_host_trigger_chain(
        snapshot,
        xiadan_running=True,
        runtime_probe={"reachable": True, "runtime_ok": False, "runtime": {"in_ths_api": False, "in_xiadan_api": False}},
    )

    assert diag["stage"] == "BRIDGE_MOCK_RUNTIME"
    assert diag["status"] == "FAIL"
    assert diag["facts"]["host_execution_evidence"] is True


def test_read_ths_account_context_returns_shape():
    context = read_ths_account_context()

    for key in (
        "ths_root",
        "ths_root_exists",
        "users_ini_exists",
        "xiadan_ini_exists",
        "last_userid",
        "last_user_name",
        "last_user_path",
        "ai_user_account",
        "sim_server_name",
        "mode_hint",
        "error",
    ):
        assert key in context

    assert isinstance(context["ths_root_exists"], bool)
    assert isinstance(context["users_ini_exists"], bool)
    assert isinstance(context["xiadan_ini_exists"], bool)


def test_summarize_trade_snapshot_success_payload():
    response = {
        "ok": True,
        "response": {
            "status": "success",
            "data": {
                "balance": {"zjye": 1000, "kyje": 900, "zzc": 1200},
                "positions": {"600000": {"kyye": 100}},
                "open_orders": [{"order_id": "A1"}],
                "full_orders": [{"order_id": "A1"}, {"order_id": "A2"}],
            },
        },
    }

    summary = summarize_trade_snapshot(response)

    assert summary["snapshot_status"] == "success"
    assert summary["has_balance"] is True
    assert summary["positions_count"] == 1
    assert summary["open_orders_count"] == 1
    assert summary["full_orders_count"] == 2
