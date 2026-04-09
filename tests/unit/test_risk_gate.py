from src.execution.base import OrderRequest, OrderSide
from src.execution.risk_gate import RiskGate


def test_single_order_limit_rejects_large_order():
    gate = RiskGate()
    request = OrderRequest(ticker="000001", side=OrderSide.BUY, price=10.0, quantity=30000)
    passed, violations = gate.check_order(
        request=request,
        total_assets=1_000_000.0,
        current_positions={},
        daily_pnl=0.0,
        is_live=False,
        simulation_days=30,
    )
    assert passed is False
    assert any(v.rule == "SINGLE_ORDER_LIMIT" for v in violations)


def test_live_trading_requires_minimum_simulation_days():
    gate = RiskGate()
    request = OrderRequest(ticker="000001", side=OrderSide.BUY, price=10.0, quantity=1000)
    passed, violations = gate.check_order(
        request=request,
        total_assets=1_000_000.0,
        current_positions={},
        daily_pnl=0.0,
        is_live=True,
        simulation_days=2,
    )
    assert passed is False
    assert any(v.rule == "SIMULATION_REQUIRED" for v in violations)


def test_risk_metrics_and_alerts_are_observable():
    gate = RiskGate()
    request = OrderRequest(ticker="000001", side=OrderSide.BUY, price=10.0, quantity=30000)
    passed, _ = gate.check_order(
        request=request,
        total_assets=1_000_000.0,
        current_positions={},
        daily_pnl=0.0,
        is_live=False,
        simulation_days=30,
    )
    assert passed is False

    metrics = gate.get_metrics()
    assert metrics["checks_total"] == 1
    assert metrics["checks_rejected"] == 1
    assert metrics["rule_hits"].get("SINGLE_ORDER_LIMIT", 0) >= 1

    alerts = gate.get_recent_alerts(limit=10)
    assert len(alerts) >= 1
    assert alerts[0]["rule"] == "SINGLE_ORDER_LIMIT"
