from __future__ import annotations

from src.core.ths_host_autostart import (
    AUTOSTART_MARK_BEGIN,
    AUTOSTART_MARK_END,
    build_autostart_injection_block,
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
    assert "def ensure_laicai_bridge_autostart" in bootstrap
    assert "import laicai_bridge as _bridge" in bootstrap


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
