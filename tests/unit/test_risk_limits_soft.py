"""
风控软规则测试（来自 config/risk_limits.toml 的可配置参数）。

覆盖：
- RiskLimits 加载与默认值
- TOTAL_POSITION_LIMIT（总仓位上限）
- HOLDING_COUNT_LIMIT（最大持股数）
- LARGE_ORDER_ALERT（大额预警，非阻断）
- check_positions 止损/止盈触发
- 软规则与硬红线协同（软规则触发时同样拒绝）
"""
from __future__ import annotations

from src.core.risk_limits import RiskLimits
from src.execution.base import OrderRequest, OrderSide
from src.execution.risk_gate import RiskGate


def _req(ticker="000001", side=OrderSide.BUY, price=10.0, quantity=100):
    return OrderRequest(ticker=ticker, side=side, price=price, quantity=quantity)


def _gate(**kwargs):
    """构造带指定软参数的 RiskGate。"""
    limits = RiskLimits(**kwargs)
    return RiskGate(risk_limits=limits)


# ---------------------------------------------------------------------------
# RiskLimits 加载
# ---------------------------------------------------------------------------


def test_risk_limits_defaults():
    lim = RiskLimits.defaults()
    assert lim.max_total_position_ratio == 0.80
    assert lim.max_sector_ratio == 0.40
    assert lim.max_holding_count == 10
    assert lim.stop_loss_percent == -0.08
    assert lim.take_profit_percent == 0.20
    assert lim.large_order_threshold == 50000.0


def test_risk_limits_from_dict_tolerates_missing_sections():
    # 空 dict 应回退到默认
    lim = RiskLimits.from_dict({})
    assert lim.max_total_position_ratio == 0.80

    # 部分字段
    lim2 = RiskLimits.from_dict({"risk": {"max_holding_count": 5}})
    assert lim2.max_holding_count == 5
    assert lim2.stop_loss_percent == -0.08  # 其他字段保持默认


def test_risk_limits_from_dict_tolerates_bad_types():
    lim = RiskLimits.from_dict({"risk": {"max_holding_count": "not-a-number"}})
    # 类型错误回退默认，不抛异常
    assert lim.max_holding_count == 10


# ---------------------------------------------------------------------------
# TOTAL_POSITION_LIMIT
# ---------------------------------------------------------------------------


def test_total_position_limit_rejects_when_exceeded():
    # 软规则：总仓位上限 50%。已持仓 40万 + 新买 20万 = 60万 / 100万 = 60% > 50%
    gate = _gate(max_total_position_ratio=0.50)
    passed, violations = gate.check_order(
        request=_req(price=10.0, quantity=20000),  # 20万
        total_assets=1_000_000.0,
        current_positions={"600519": 400_000.0},
        daily_pnl=0.0, is_live=False, simulation_days=30,
        position_count=1,
        total_position_value=400_000.0,
    )
    assert passed is False
    assert any(v.rule == "TOTAL_POSITION_LIMIT" for v in violations)


def test_total_position_limit_allows_within_limit():
    gate = _gate(max_total_position_ratio=0.80)
    passed, _ = gate.check_order(
        request=_req(price=10.0, quantity=1000),  # 1万
        total_assets=1_000_000.0,
        current_positions={},
        daily_pnl=0.0, is_live=False, simulation_days=30,
        position_count=0,
        total_position_value=0.0,
    )
    assert passed is True


def test_total_position_not_checked_for_sell():
    gate = _gate(max_total_position_ratio=0.10)  # 极低上限
    # 卖出不应触发总仓位上限（卖出减仓）
    passed, violations = gate.check_order(
        request=_req(side=OrderSide.SELL, price=10.0, quantity=100000),
        total_assets=1_000_000.0,
        current_positions={"000001": 500_000.0},
        daily_pnl=0.0, is_live=False, simulation_days=30,
        position_count=1,
        total_position_value=500_000.0,
    )
    assert not any(v.rule == "TOTAL_POSITION_LIMIT" for v in violations)


# ---------------------------------------------------------------------------
# HOLDING_COUNT_LIMIT
# ---------------------------------------------------------------------------


def test_holding_count_limit_rejects_new_position_beyond_limit():
    # 已持有 10 只股票（上限 10），再买一只新的（第 11 只）应被拒
    existing = {f"60000{i}": 50_000.0 for i in range(10)}
    gate = _gate(max_holding_count=10)
    passed, violations = gate.check_order(
        request=_req(ticker="300999", price=10.0, quantity=100),  # 新标的
        total_assets=2_000_000.0,
        current_positions=existing,
        daily_pnl=0.0, is_live=False, simulation_days=30,
        position_count=10,
        total_position_value=sum(existing.values()),
    )
    assert passed is False
    assert any(v.rule == "HOLDING_COUNT_LIMIT" for v in violations)


def test_holding_count_limit_allows_adding_to_existing_position():
    # 已持有 10 只，但买入的是已有的标的（不加新持股数），应放行
    existing = {f"60000{i}": 50_000.0 for i in range(10)}
    gate = _gate(max_holding_count=10)
    passed, _ = gate.check_order(
        request=_req(ticker="600000", price=10.0, quantity=100),  # 已持有
        total_assets=2_000_000.0,
        current_positions=existing,
        daily_pnl=0.0, is_live=False, simulation_days=30,
        position_count=10,
        total_position_value=sum(existing.values()),
    )
    assert passed is True


# ---------------------------------------------------------------------------
# LARGE_ORDER_ALERT（非阻断）
# ---------------------------------------------------------------------------


def test_large_order_alert_does_not_block():
    # 大额预警阈值 5万，订单 6万 > 5万，但应仅告警不阻断
    gate = _gate(large_order_threshold=50000.0)
    passed, violations = gate.check_order(
        request=_req(price=10.0, quantity=6000),  # 6万
        total_assets=10_000_000.0,  # 大资产避免触发单笔限额
        current_positions={},
        daily_pnl=0.0, is_live=False, simulation_days=30,
        position_count=0,
        total_position_value=0.0,
    )
    # 不阻断
    assert passed is True
    assert not any(v.rule == "LARGE_ORDER_ALERT" for v in violations)
    # 但告警已记录到 alerts
    alerts = gate.get_recent_alerts()
    assert any(a["rule"] == "LARGE_ORDER_ALERT" for a in alerts)


# ---------------------------------------------------------------------------
# check_positions 止损/止盈
# ---------------------------------------------------------------------------


def test_check_positions_triggers_stop_loss():
    gate = _gate(stop_loss_percent=-0.08, take_profit_percent=0.20)
    positions = [
        {"ticker": "000001", "avg_cost": 10.0, "current_price": 9.0, "market_value": 9000.0},  # -10% 触止损
    ]
    triggered = gate.check_positions(positions)
    assert len(triggered) == 1
    assert triggered[0].rule == "STOP_LOSS_TRIGGERED"
    assert triggered[0].value <= -0.08


def test_check_positions_triggers_take_profit():
    gate = _gate(stop_loss_percent=-0.08, take_profit_percent=0.20)
    positions = [
        {"ticker": "000001", "avg_cost": 10.0, "current_price": 12.5, "market_value": 12500.0},  # +25% 触止盈
    ]
    triggered = gate.check_positions(positions)
    assert len(triggered) == 1
    assert triggered[0].rule == "TAKE_PROFIT_TRIGGERED"


def test_check_positions_no_trigger_within_range():
    gate = _gate(stop_loss_percent=-0.08, take_profit_percent=0.20)
    positions = [
        {"ticker": "000001", "avg_cost": 10.0, "current_price": 10.5, "market_value": 10500.0},  # +5% 正常
    ]
    triggered = gate.check_positions(positions)
    assert triggered == []


def test_check_positions_skips_invalid_cost():
    """avg_cost 或 current_price 为 0 时跳过（避免除零）。"""
    gate = _gate()
    positions = [
        {"ticker": "000001", "avg_cost": 0.0, "current_price": 10.0, "market_value": 0.0},
        {"ticker": "000002", "avg_cost": 10.0, "current_price": 0.0, "market_value": 0.0},
    ]
    triggered = gate.check_positions(positions)
    assert triggered == []


def test_check_positions_mixed_batch():
    """多持仓混合：一个止损、一个止盈、一个正常。"""
    gate = _gate(stop_loss_percent=-0.08, take_profit_percent=0.20)
    positions = [
        {"ticker": "000001", "avg_cost": 10.0, "current_price": 9.0, "market_value": 9000.0},   # -10% 止损
        {"ticker": "000002", "avg_cost": 10.0, "current_price": 12.5, "market_value": 12500.0},  # +25% 止盈
        {"ticker": "000003", "avg_cost": 10.0, "current_price": 10.0, "market_value": 10000.0},  # 0% 正常
    ]
    triggered = gate.check_positions(positions)
    rules = {t.rule for t in triggered}
    assert rules == {"STOP_LOSS_TRIGGERED", "TAKE_PROFIT_TRIGGERED"}


# ---------------------------------------------------------------------------
# 软规则与硬红线协同
# ---------------------------------------------------------------------------


def test_soft_rule_and_hard_rule_both_reported():
    """软规则触发时，硬红线检查仍正常工作，两者可同时出现在 violations。"""
    gate = _gate(max_total_position_ratio=0.10, max_holding_count=10)
    # 单笔 30万 / 100万 = 30% > 20%（硬红线 SINGLE_ORDER_LIMIT）
    # 同时总仓位也超 10%（软规则）
    passed, violations = gate.check_order(
        request=_req(price=10.0, quantity=30000),
        total_assets=1_000_000.0,
        current_positions={},
        daily_pnl=0.0, is_live=False, simulation_days=30,
        position_count=0,
        total_position_value=0.0,
    )
    assert passed is False
    rules = {v.rule for v in violations}
    assert "SINGLE_ORDER_LIMIT" in rules  # 硬红线
    assert "TOTAL_POSITION_LIMIT" in rules  # 软规则
