from __future__ import annotations

from src.core.degrade_policy import build_default_degrade_policy


def test_default_policy_matches_realtime_price_rule(monkeypatch):
    monkeypatch.delenv("TRADE_DEGRADE_DISABLED_RULES", raising=False)
    policy = build_default_degrade_policy()
    state = {
        "context": {
            "realtime": {"price": 0.0},
            "news_sentiment": {"status": "ok"},
        },
        "analysis_reports": {},
        "trading_decision": {"reason": "normal"},
    }

    result = policy.evaluate(state)
    assert result["should_degrade"] is True
    assert "realtime_price_unavailable" in result["degrade_flags"]
    assert result["recommended_action"] == "force_hold"
    assert result["should_force_hold"] is True


def test_policy_can_disable_specific_rule(monkeypatch):
    monkeypatch.setenv("TRADE_DEGRADE_DISABLED_RULES", "realtime_price_unavailable")
    policy = build_default_degrade_policy()
    state = {
        "context": {
            "realtime": {"price": 0.0},
            "news_sentiment": {"status": "ok"},
        },
        "analysis_reports": {},
        "trading_decision": {"reason": "normal"},
    }

    result = policy.evaluate(state)
    assert "realtime_price_unavailable" not in result["degrade_flags"]
    assert result["should_degrade"] is False
    assert result["recommended_action"] == "none"


def test_dataflow_quality_rule_uses_alert_levels(monkeypatch):
    monkeypatch.setenv("TRADE_DEGRADE_DATAFLOW_ALERT_LEVELS", "critical,warn")
    policy = build_default_degrade_policy()
    state = {
        "context": {
            "realtime": {"price": 10.0},
            "news_sentiment": {"status": "ok"},
            "dataflow_quality": {"alert_level": "warn"},
        },
        "analysis_reports": {},
        "trading_decision": {"reason": "normal"},
    }

    result = policy.evaluate(state)
    assert result["should_degrade"] is True
    assert "dataflow_quality_critical" in result["degrade_flags"]


def test_llm_latency_rule_can_be_warn_only(monkeypatch):
    monkeypatch.setenv("TRADE_DEGRADE_ENABLED_RULES", "llm_latency_exceeded")
    monkeypatch.setenv("TRADE_DEGRADE_LLM_LATENCY_ACTION", "warn_only")
    policy = build_default_degrade_policy()
    state = {
        "context": {
            "realtime": {"price": 10.0},
            "llm_runtime": {"latency_exceeded_count": 1, "last_flags": ["latency_exceeded"]},
        },
        "analysis_reports": {},
        "trading_decision": {"reason": "normal"},
    }
    result = policy.evaluate(state)
    assert result["should_degrade"] is True
    assert result["recommended_action"] == "warn_only"
    assert result["should_force_hold"] is False
    assert result["should_warn"] is True


def test_conflict_strategy_highest_priority_prefers_priority_override(monkeypatch):
    monkeypatch.setenv("TRADE_DEGRADE_ENABLED_RULES", "realtime_price_unavailable,llm_latency_exceeded")
    monkeypatch.setenv("TRADE_DEGRADE_CONFLICT_STRATEGY", "highest_priority")
    monkeypatch.setenv("TRADE_DEGRADE_LLM_LATENCY_ACTION", "warn_only")
    monkeypatch.setenv("TRADE_DEGRADE_RULE_PRIORITIES", "llm_latency_exceeded:200,realtime_price_unavailable:50")
    policy = build_default_degrade_policy()
    state = {
        "context": {
            "realtime": {"price": 0.0},
            "llm_runtime": {"latency_exceeded_count": 1, "last_flags": ["latency_exceeded"]},
        },
        "analysis_reports": {},
        "trading_decision": {"reason": "normal"},
    }
    result = policy.evaluate(state)
    assert result["conflict_strategy"] == "highest_priority"
    assert result["recommended_action"] == "warn_only"
    assert result["degrade_flags"] == ["llm_latency_exceeded"]
    assert result["selected_rules"][0]["priority"] == 200


def test_conflict_strategy_highest_action_prefers_force_hold(monkeypatch):
    monkeypatch.setenv("TRADE_DEGRADE_ENABLED_RULES", "realtime_price_unavailable,llm_latency_exceeded")
    monkeypatch.setenv("TRADE_DEGRADE_CONFLICT_STRATEGY", "highest_action")
    monkeypatch.setenv("TRADE_DEGRADE_LLM_LATENCY_ACTION", "warn_only")
    monkeypatch.setenv("TRADE_DEGRADE_RULE_PRIORITIES", "llm_latency_exceeded:200,realtime_price_unavailable:50")
    policy = build_default_degrade_policy()
    state = {
        "context": {
            "realtime": {"price": 0.0},
            "llm_runtime": {"latency_exceeded_count": 1, "last_flags": ["latency_exceeded"]},
        },
        "analysis_reports": {},
        "trading_decision": {"reason": "normal"},
    }
    result = policy.evaluate(state)
    assert result["conflict_strategy"] == "highest_action"
    assert result["recommended_action"] == "force_hold"
    assert "realtime_price_unavailable" in result["degrade_flags"]
