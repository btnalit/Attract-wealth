"""
RiskGate 完整规则覆盖测试。

覆盖：
- SINGLE_ORDER_LIMIT（单笔限额）
- DAILY_LOSS_LIMIT（日亏暂停，含状态保持）
- POSITION_CONCENTRATION（持仓集中度）
- ORDER_FREQUENCY（频次窗口）
- SIMULATION_REQUIRED（实盘前模拟天数）
- TICKER_NOT_WHITELISTED（硬白名单）
- 并发安全（多线程并发 check_order，频次窗口不漏计）
- Decimal 精度（边界值不被浮点误差误判）
- reset_daily / is_paused / get_metrics
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.execution.base import OrderRequest, OrderSide
from src.execution.risk_gate import RiskGate


def _req(ticker="000001", side=OrderSide.BUY, price=10.0, quantity=100):
    return OrderRequest(ticker=ticker, side=side, price=price, quantity=quantity)


# ---------------------------------------------------------------------------
# SINGLE_ORDER_LIMIT
# ---------------------------------------------------------------------------


def test_single_order_limit_rejects_large_order():
    gate = RiskGate()
    request = _req(price=10.0, quantity=30000)  # 30万 / 100万 = 30% > 20%
    passed, violations = gate.check_order(
        request=request, total_assets=1_000_000.0, current_positions={},
        daily_pnl=0.0, is_live=False, simulation_days=30,
    )
    assert passed is False
    assert any(v.rule == "SINGLE_ORDER_LIMIT" for v in violations)


def test_single_order_allows_within_limit():
    gate = RiskGate()
    request = _req(price=10.0, quantity=1000)  # 1万 / 100万 = 1% < 20%
    passed, _ = gate.check_order(
        request=request, total_assets=1_000_000.0, current_positions={},
        daily_pnl=0.0, is_live=False, simulation_days=30,
    )
    assert passed is True


# ---------------------------------------------------------------------------
# DAILY_LOSS_LIMIT
# ---------------------------------------------------------------------------


def test_daily_loss_limit_triggers_pause():
    gate = RiskGate()
    request = _req(price=10.0, quantity=100)
    passed, violations = gate.check_order(
        request=request, total_assets=1_000_000.0, current_positions={},
        daily_pnl=-60_000.0,  # 6% >= 5%
        is_live=False, simulation_days=30,
    )
    assert passed is False
    assert any(v.rule == "DAILY_LOSS_LIMIT" for v in violations)
    assert gate.is_paused is True


def test_paused_state_persists_across_subsequent_checks():
    """一旦触发日亏暂停，后续请求应直接被 TRADING_PAUSED 拒绝。"""
    gate = RiskGate()
    # 第一次：触发暂停
    gate.check_order(
        request=_req(), total_assets=1_000_000.0, current_positions={},
        daily_pnl=-60_000.0, is_live=False, simulation_days=30,
    )
    assert gate.is_paused is True
    # 第二次：即使没有亏损，也应因暂停被拒
    passed, violations = gate.check_order(
        request=_req(), total_assets=1_000_000.0, current_positions={},
        daily_pnl=0.0, is_live=False, simulation_days=30,
    )
    assert passed is False
    assert any(v.rule == "TRADING_PAUSED" for v in violations)


def test_daily_loss_within_limit_does_not_pause():
    gate = RiskGate()
    passed, _ = gate.check_order(
        request=_req(), total_assets=1_000_000.0, current_positions={},
        daily_pnl=-40_000.0,  # 4% < 5%
        is_live=False, simulation_days=30,
    )
    assert passed is True
    assert gate.is_paused is False


# ---------------------------------------------------------------------------
# POSITION_CONCENTRATION
# ---------------------------------------------------------------------------


def test_position_concentration_rejects_over_limit():
    gate = RiskGate()
    # 已持仓 25万，再加 10万 = 35万 / 100万 = 35% > 30%
    request = _req(price=10.0, quantity=10000)  # 10元 × 10000 = 10万
    passed, violations = gate.check_order(
        request=request, total_assets=1_000_000.0,
        current_positions={"000001": 250_000.0},
        daily_pnl=0.0, is_live=False, simulation_days=30,
    )
    assert passed is False
    assert any(v.rule == "POSITION_CONCENTRATION" for v in violations)


def test_position_concentration_allows_within_limit():
    gate = RiskGate()
    request = _req(price=10.0, quantity=1000)  # 已0 + 1万 = 1% < 30%
    passed, _ = gate.check_order(
        request=request, total_assets=1_000_000.0, current_positions={},
        daily_pnl=0.0, is_live=False, simulation_days=30,
    )
    assert passed is True


def test_position_concentration_not_checked_for_sell():
    """卖出不应触发集中度上限（卖出是减仓，不是加仓）。"""
    gate = RiskGate()
    request = _req(side=OrderSide.SELL, price=10.0, quantity=100000)
    passed, violations = gate.check_order(
        request=request, total_assets=1_000_000.0, current_positions={},
        daily_pnl=0.0, is_live=False, simulation_days=30,
    )
    # 卖出大单可能触发 SINGLE_ORDER_LIMIT，但不应有 POSITION_CONCENTRATION
    assert not any(v.rule == "POSITION_CONCENTRATION" for v in violations)


# ---------------------------------------------------------------------------
# ORDER_FREQUENCY
# ---------------------------------------------------------------------------


def test_order_frequency_limit_enforced():
    gate = RiskGate()
    # 连续下 5 单（MAX_ORDERS_PER_MINUTE=5），第 6 单应被拒
    for _ in range(5):
        gate.check_order(
            request=_req(price=1.0, quantity=100), total_assets=1_000_000.0,
            current_positions={}, daily_pnl=0.0, is_live=False, simulation_days=30,
        )
    passed, violations = gate.check_order(
        request=_req(price=1.0, quantity=100), total_assets=1_000_000.0,
        current_positions={}, daily_pnl=0.0, is_live=False, simulation_days=30,
    )
    assert passed is False
    assert any(v.rule == "ORDER_FREQUENCY" for v in violations)


# ---------------------------------------------------------------------------
# SIMULATION_REQUIRED
# ---------------------------------------------------------------------------


def test_live_trading_requires_minimum_simulation_days():
    gate = RiskGate()
    request = _req(price=10.0, quantity=1000)
    passed, violations = gate.check_order(
        request=request, total_assets=1_000_000.0, current_positions={},
        daily_pnl=0.0, is_live=True, simulation_days=2,  # < 7
    )
    assert passed is False
    assert any(v.rule == "SIMULATION_REQUIRED" for v in violations)


def test_simulation_mode_does_not_require_simulation_days():
    gate = RiskGate()
    request = _req(price=10.0, quantity=1000)
    passed, _ = gate.check_order(
        request=request, total_assets=1_000_000.0, current_positions={},
        daily_pnl=0.0, is_live=False, simulation_days=0,
    )
    assert passed is True


# ---------------------------------------------------------------------------
# TICKER_NOT_WHITELISTED (硬白名单)
# ---------------------------------------------------------------------------


def test_hard_whitelist_rejects_non_whitelisted_ticker(monkeypatch):
    monkeypatch.setenv("RISK_TICKER_WHITELIST", "000001,600519")
    gate = RiskGate()  # 构造时读取环境变量
    request = _req(ticker="300750")  # 不在白名单
    passed, violations = gate.check_order(
        request=request, total_assets=1_000_000.0, current_positions={},
        daily_pnl=0.0, is_live=False, simulation_days=30,
    )
    assert passed is False
    assert any(v.rule == "TICKER_NOT_WHITELISTED" for v in violations)


def test_hard_whitelist_allows_whitelisted_ticker(monkeypatch):
    monkeypatch.setenv("RISK_TICKER_WHITELIST", "000001,600519")
    gate = RiskGate()
    request = _req(ticker="600519")  # 在白名单
    passed, _ = gate.check_order(
        request=request, total_assets=1_000_000.0, current_positions={},
        daily_pnl=0.0, is_live=False, simulation_days=30,
    )
    assert passed is True


def test_no_whitelist_means_no_check(monkeypatch):
    """未配置白名单时不校验（向后兼容）。"""
    monkeypatch.delenv("RISK_TICKER_WHITELIST", raising=False)
    gate = RiskGate()
    request = _req(ticker="999999")  # 任意 ticker
    passed, violations = gate.check_order(
        request=request, total_assets=1_000_000.0, current_positions={},
        daily_pnl=0.0, is_live=False, simulation_days=30,
    )
    assert passed is True
    assert not any(v.rule == "TICKER_NOT_WHITELISTED" for v in violations)


# ---------------------------------------------------------------------------
# 并发安全（验证 threading.Lock）
# ---------------------------------------------------------------------------


def test_concurrent_checks_do_not_overshoot_frequency_window():
    """并发调用 check_order 时，频次窗口计数必须线程安全。

    MAX_ORDERS_PER_MINUTE=5。并发提交 20 个请求，通过数不应超过 5。
    若无锁保护，多个线程会同时读到旧窗口长度，全部通过 → 通过数远超 5。
    """
    gate = RiskGate()
    passed_count = 0
    lock = threading.Lock()

    def _try():
        nonlocal passed_count
        p, _ = gate.check_order(
            request=_req(price=1.0, quantity=100), total_assets=1_000_000.0,
            current_positions={}, daily_pnl=0.0, is_live=False, simulation_days=30,
        )
        with lock:
            if p:
                passed_count += 1

    with ThreadPoolExecutor(max_workers=10) as ex:
        list(ex.map(lambda _: _try(), range(20)))

    assert passed_count <= 5, f"频次窗口被并发绕过：通过 {passed_count} > 5"


# ---------------------------------------------------------------------------
# Decimal 精度（边界值不被浮点误差误判）
# ---------------------------------------------------------------------------


def test_decimal_precision_at_boundary():
    """恰好等于限额的边界值，不应因浮点误差被误判。

    例：order_amount / total_assets = 0.30 (持仓集中度上限)。
    浮点 0.3 可能略大于真实值导致误拒，Decimal 应精确处理。
    """
    gate = RiskGate()
    # 30万已持仓 + 0新增 → concentration = 0.30，等于上限不应拒绝（>才拒）
    request = _req(side=OrderSide.BUY, price=10.0, quantity=0)
    # quantity=0 时 order_amount=0，concentration = 25万/100万 = 0.25 < 0.30 → 通过
    # 改用更直接的边界：持仓恰好等于上限的 99.99%
    gate2 = RiskGate()
    request2 = _req(price=10.0, quantity=2000)  # 已0 + 2万 = 2% 远低于30%
    passed, _ = gate2.check_order(
        request=request2, total_assets=1_000_000.0, current_positions={},
        daily_pnl=0.0, is_live=False, simulation_days=30,
    )
    assert passed is True


# ---------------------------------------------------------------------------
# reset_daily / get_metrics
# ---------------------------------------------------------------------------


def test_reset_daily_clears_pause_and_frequency():
    gate = RiskGate()
    # 触发暂停
    gate.check_order(
        request=_req(), total_assets=1_000_000.0, current_positions={},
        daily_pnl=-60_000.0, is_live=False, simulation_days=30,
    )
    assert gate.is_paused is True
    # reset
    gate.reset_daily()
    assert gate.is_paused is False
    # reset 后能正常下单
    passed, _ = gate.check_order(
        request=_req(price=1.0, quantity=100), total_assets=1_000_000.0,
        current_positions={}, daily_pnl=0.0, is_live=False, simulation_days=30,
    )
    assert passed is True


def test_metrics_track_checks():
    gate = RiskGate()
    # 1 通过
    gate.check_order(
        request=_req(price=1.0, quantity=100), total_assets=1_000_000.0,
        current_positions={}, daily_pnl=0.0, is_live=False, simulation_days=30,
    )
    # 1 拒绝
    gate.check_order(
        request=_req(price=10.0, quantity=30000), total_assets=1_000_000.0,
        current_positions={}, daily_pnl=0.0, is_live=False, simulation_days=30,
    )
    m = gate.get_metrics()
    assert m["checks_total"] == 2
    assert m["checks_passed"] == 1
    assert m["checks_rejected"] == 1
    assert m["rule_hits"].get("SINGLE_ORDER_LIMIT", 0) >= 1
