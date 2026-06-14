from __future__ import annotations

from src.agents.risk_mgmt.risk_manager import RiskManager


def _build_state(*, action: str, percentage: float, ticker: str = "000001", total_assets: float = 1_000_000.0, market_value: float = 0.0):
    return {
        "ticker": ticker,
        "trading_decision": {
            "action": action,
            "percentage": percentage,
        },
        "context": {
            "portfolio": {
                "total_assets": total_assets,
                "positions": {
                    ticker: {
                        "market_value": market_value,
                    }
                },
            }
        },
    }


def test_risk_manager_rejects_single_order_over_limit():
    manager = RiskManager(max_single_stock_percent=30.0)
    manager._log_rejection = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

    result = manager.check_risk(_build_state(action="BUY", percentage=35.0))
    assert result["risk_check"]["passed"] is False
    assert "exceeds" in result["risk_check"]["reason"]


def test_risk_manager_rejects_projected_total_position_over_limit():
    manager = RiskManager(max_single_stock_percent=30.0)
    manager._log_rejection = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

    state = _build_state(action="BUY", percentage=15.0, total_assets=1_000_000.0, market_value=200_000.0)
    result = manager.check_risk(state)
    assert result["risk_check"]["passed"] is False
    assert "Projected position" in result["risk_check"]["reason"]


def test_risk_manager_allows_projected_total_position_within_limit():
    manager = RiskManager(max_single_stock_percent=30.0)
    state = _build_state(action="BUY", percentage=8.0, total_assets=1_000_000.0, market_value=120_000.0)

    result = manager.check_risk(state)
    assert result["risk_check"]["passed"] is True
    assert result["risk_check"]["reason"] == "All checks cleared"


def test_risk_manager_missing_portfolio_still_passes_with_warning(caplog):
    """G7-6：无组合数据（total_assets<=0）时，集中度叠加检查降级跳过，
    但单笔上限（Rule 2）仍生效。中等比例买入应放行（硬层 RiskGate 兜底）。"""
    manager = RiskManager(max_single_stock_percent=30.0)
    manager._log_rejection = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

    state = _build_state(action="BUY", percentage=15.0, total_assets=0.0, market_value=0.0)
    import logging
    with caplog.at_level(logging.WARNING):
        result = manager.check_risk(state)

    # 无组合数据时，中等比例买入应放行（Rule 3 降级，Rule 2 未触及 30%）
    assert result["risk_check"]["passed"] is True
    # 应有 degrade 警告日志
    assert any("concentration check skipped" in rec.message for rec in caplog.records)


def test_risk_manager_missing_portfolio_still_enforces_single_order_limit():
    """G7-6：即使无组合数据，单笔超过 max_single_stock_percent 仍拒绝（Rule 2）。"""
    manager = RiskManager(max_single_stock_percent=30.0)
    manager._log_rejection = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

    state = _build_state(action="BUY", percentage=50.0, total_assets=0.0)
    result = manager.check_risk(state)
    assert result["risk_check"]["passed"] is False
    assert "exceeds max single-stock limit" in result["risk_check"]["reason"]

