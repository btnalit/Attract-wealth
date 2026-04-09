from __future__ import annotations

import uuid

from src.core.storage import init_all_databases
from src.core.trading_ledger import TradeRecord, TradingLedger


def test_update_trade_status_is_idempotent():
    init_all_databases()
    trade_id = f"unit-{uuid.uuid4().hex[:10]}"
    TradingLedger.record_trade(
        TradeRecord(
            id=trade_id,
            ticker="000001",
            action="BUY",
            price=10.0,
            quantity=100,
            status="submitted",
            channel="simulation",
        )
    )

    same = TradingLedger.update_trade_status(
        trade_id=trade_id,
        status="submitted",
        filled_price=0.0,
        filled_quantity=0,
    )
    assert same["updated"] is False

    changed = TradingLedger.update_trade_status(
        trade_id=trade_id,
        status="partial",
        filled_price=10.0,
        filled_quantity=50,
    )
    assert changed["updated"] is True

    same_again = TradingLedger.update_trade_status(
        trade_id=trade_id,
        status="partial",
        filled_price=10.0,
        filled_quantity=50,
    )
    assert same_again["updated"] is False


def test_record_and_list_decision_evidence():
    init_all_databases()
    session_id = f"sess-{uuid.uuid4().hex[:8]}"
    evidence_id = TradingLedger.record_decision_evidence(
        {
            "session_id": session_id,
            "ticker": "000001",
            "phase": "execute",
            "channel": "simulation",
            "decision": "BUY",
            "confidence": 88.0,
            "action": "BUY",
            "percentage": 10.0,
            "reason": "unit test",
            "risk_check": {"passed": True, "reason": "ok"},
            "analysis_reports": {"technical": {"summary": "ok"}},
        }
    )
    rows = TradingLedger.list_decision_evidence(session_id=session_id, limit=5)
    assert any(item["id"] == evidence_id for item in rows)


def test_list_decision_evidence_with_request_and_degraded_filters():
    init_all_databases()
    session_id = f"sess-{uuid.uuid4().hex[:8]}"
    request_id = f"req-{uuid.uuid4().hex[:8]}"
    TradingLedger.record_decision_evidence(
        {
            "session_id": session_id,
            "request_id": request_id,
            "ticker": "000001",
            "phase": "execute",
            "channel": "simulation",
            "decision": "HOLD",
            "confidence": 30.0,
            "action": "HOLD",
            "percentage": 0.0,
            "reason": "degraded test",
            "degrade_flags": ["realtime_price_unavailable"],
            "degrade_policy": {"matched_rules": [{"rule_id": "realtime_price_unavailable"}]},
            "trace": {"request_id": request_id, "trace_id": "trace-1"},
        }
    )
    TradingLedger.record_decision_evidence(
        {
            "session_id": session_id,
            "request_id": "other-req",
            "ticker": "000001",
            "phase": "analyze",
            "channel": "simulation",
            "decision": "BUY",
            "confidence": 80.0,
            "action": "BUY",
            "percentage": 10.0,
            "reason": "normal",
            "degrade_flags": [],
            "trace": {"request_id": "other-req", "trace_id": "trace-2"},
        }
    )

    filtered = TradingLedger.list_decision_evidence(
        limit=10,
        request_id=request_id,
        degraded_only=True,
        phase="execute",
    )
    assert len(filtered) >= 1
    assert all(item["request_id"] == request_id for item in filtered)
    assert all(item["degraded"] is True for item in filtered)


def test_record_llm_usage_and_summary():
    init_all_databases()
    session_id = f"llm-{uuid.uuid4().hex[:8]}"
    TradingLedger.record_llm_usage(
        {
            "session_id": session_id,
            "agent_id": "unit-agent",
            "provider": "https://api.test",
            "model": "test-model",
            "input_tokens": 120,
            "output_tokens": 30,
            "cost_usd": 0.012,
        }
    )
    summary = TradingLedger.get_llm_usage_summary(hours=24, session_id=session_id)
    assert summary["call_count"] == 1
    assert summary["total_tokens"] == 150
    assert summary["cost_usd"] == 0.012


def test_build_portfolio_snapshot_filters_by_channel():
    init_all_databases()
    sim_ticker = f"SIM{uuid.uuid4().hex[:4]}".upper()
    ths_ticker = f"THS{uuid.uuid4().hex[:4]}".upper()

    # simulation channel trade
    TradingLedger.record_trade(
        TradeRecord(
            id=f"sim-{uuid.uuid4().hex[:10]}",
            ticker=sim_ticker,
            action="BUY",
            price=10.0,
            quantity=100,
            filled_quantity=100,
            amount=1000.0,
            commission=1.0,
            status="filled",
            channel="simulation",
        )
    )
    # ths_ipc channel trade
    TradingLedger.record_trade(
        TradeRecord(
            id=f"ths-{uuid.uuid4().hex[:10]}",
            ticker=ths_ticker,
            action="BUY",
            price=20.0,
            quantity=50,
            filled_quantity=50,
            amount=1000.0,
            commission=1.0,
            status="filled",
            channel="ths_ipc",
        )
    )

    all_snapshot = TradingLedger.build_portfolio_snapshot(initial_cash=10000.0)
    sim_snapshot = TradingLedger.build_portfolio_snapshot(initial_cash=10000.0, channel="simulation")
    ths_snapshot = TradingLedger.build_portfolio_snapshot(initial_cash=10000.0, channel="ths_ipc")

    assert all_snapshot["positions"].get(sim_ticker, 0) >= 100
    assert all_snapshot["positions"].get(ths_ticker, 0) >= 50
    assert sim_snapshot["positions"].get(sim_ticker, 0) >= 100
    assert sim_snapshot["positions"].get(ths_ticker, 0) == 0
    assert ths_snapshot["positions"].get(ths_ticker, 0) >= 50
    assert ths_snapshot["positions"].get(sim_ticker, 0) == 0
