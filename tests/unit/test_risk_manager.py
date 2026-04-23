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
