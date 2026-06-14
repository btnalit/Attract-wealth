"""A 股市场硬规则测试（手数/最小变动价位/涨跌停）。

验证 RiskGate 对中国大陆股票市场通用规则的强制执行。
"""
from __future__ import annotations

from src.execution.base import OrderRequest, OrderSide
from src.execution.risk_gate import RiskGate


def _req(ticker="000001", side=OrderSide.BUY, price=10.0, quantity=100, market="CN"):
    return OrderRequest(ticker=ticker, side=side, price=price, quantity=quantity, market=market)


def _check(gate, request, **kwargs):
    """便捷调用，返回 (passed, violations)。"""
    return gate.check_order(
        request=request,
        total_assets=kwargs.get("total_assets", 1_000_000.0),
        current_positions=kwargs.get("current_positions", {}),
        daily_pnl=0.0,
        is_live=False,
        simulation_days=30,
        position_count=kwargs.get("position_count", 0),
        total_position_value=kwargs.get("total_position_value", 0.0),
        prev_close=kwargs.get("prev_close"),
    )


# ---------------------------------------------------------------------------
# 手数校验（100 股整数倍）
# ---------------------------------------------------------------------------


def test_lot_size_rejects_non_multiple_of_100():
    gate = RiskGate()
    # 150 股不是 100 的倍数
    passed, violations = _check(gate, _req(quantity=150))
    assert passed is False
    assert any(v.rule == "INVALID_LOT_SIZE" for v in violations)


def test_lot_size_rejects_odd_shares():
    gate = RiskGate()
    passed, violations = _check(gate, _req(quantity=99))
    assert passed is False
    assert any(v.rule == "INVALID_LOT_SIZE" for v in violations)


def test_lot_size_accepts_exact_100():
    gate = RiskGate()
    passed, _ = _check(gate, _req(quantity=100))
    assert passed is True


def test_lot_size_accepts_multiple_of_100():
    gate = RiskGate()
    passed, _ = _check(gate, _req(quantity=1000))
    assert passed is True


def test_lot_size_rejects_zero():
    gate = RiskGate()
    passed, violations = _check(gate, _req(quantity=0))
    assert passed is False
    assert any(v.rule == "INVALID_LOT_SIZE" for v in violations)


# ---------------------------------------------------------------------------
# 最小报价变动（0.01 元整数倍）
# ---------------------------------------------------------------------------


def test_price_tick_rejects_sub_cent():
    gate = RiskGate()
    # 10.005 不是 0.01 的整数倍
    passed, violations = _check(gate, _req(price=10.005))
    assert passed is False
    assert any(v.rule == "INVALID_PRICE_TICK" for v in violations)


def test_price_tick_accepts_exact_cent():
    gate = RiskGate()
    passed, _ = _check(gate, _req(price=10.01))
    assert passed is True


def test_price_tick_rejects_negative():
    gate = RiskGate()
    passed, violations = _check(gate, _req(price=-1.0))
    assert passed is False
    # 负价同时触发 INVALID_PRICE_TICK
    assert any(v.rule == "INVALID_PRICE_TICK" for v in violations)


# ---------------------------------------------------------------------------
# 涨跌停校验（需提供 prev_close）
# ---------------------------------------------------------------------------


def test_limit_up_rejects_price_above_10pct():
    gate = RiskGate()
    # 昨收 10.00，涨停 11.00。委托 11.50 应被拒
    passed, violations = _check(gate, _req(price=11.50), prev_close=10.00)
    assert passed is False
    assert any(v.rule == "PRICE_ABOVE_LIMIT_UP" for v in violations)


def test_limit_down_rejects_price_below_10pct():
    gate = RiskGate()
    # 昨收 10.00，跌停 9.00。委托 8.50 应被拒
    passed, violations = _check(gate, _req(price=8.50), prev_close=10.00)
    assert passed is False
    assert any(v.rule == "PRICE_BELOW_LIMIT_DOWN" for v in violations)


def test_limit_allows_within_band():
    gate = RiskGate()
    # 昨收 10.00，涨跌停 9.00-11.00。委托 10.50 应通过
    passed, _ = _check(gate, _req(price=10.50), prev_close=10.00)
    assert passed is True


def test_limit_allows_exact_limit_up_price():
    """恰好等于涨停价（11.00）应通过（A 股涨停价是可成交的）。"""
    gate = RiskGate()
    passed, _ = _check(gate, _req(price=11.00), prev_close=10.00)
    assert passed is True


def test_no_prev_close_skips_limit_check():
    """未提供昨收价时跳过涨跌停校验（向后兼容）。"""
    gate = RiskGate()
    # 即使价格离谱，没有 prev_close 也不校验涨跌停
    passed, _ = _check(gate, _req(price=999.99))
    assert passed is True


# ---------------------------------------------------------------------------
# 组合：多条 A 股规则同时违反
# ---------------------------------------------------------------------------


def test_multiple_ashare_violations_reported():
    """手数不对 + 价格不合规 + 超涨停，三条应同时报告。"""
    gate = RiskGate()
    passed, violations = _check(gate, _req(quantity=150, price=12.005), prev_close=10.00)
    assert passed is False
    rules = {v.rule for v in violations}
    assert "INVALID_LOT_SIZE" in rules
    assert "INVALID_PRICE_TICK" in rules
    assert "PRICE_ABOVE_LIMIT_UP" in rules
