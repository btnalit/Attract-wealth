from __future__ import annotations

import asyncio
import uuid
from typing import Any

from src.core.storage import init_all_databases
from src.core.trading_ledger import TradingLedger
from src.llm.openai_compat import LLMConfig, UnifiedLLMClient


class _FakeResponse:
    def __init__(self, *, model: str, content: str, prompt_tokens: int, completion_tokens: int):
        self.model = model
        self.usage = type(
            "Usage",
            (),
            {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        )()
        message = type("Message", (), {"content": content})()
        self.choices = [type("Choice", (), {"message": message})()]


class _FakeCompletions:
    def __init__(self, responses: list[Any]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class _FakeClient:
    def __init__(self, responses: list[Any]):
        completions = _FakeCompletions(responses)
        self.completions = completions
        self.chat = type("Chat", (), {"completions": completions})()


def test_llm_cost_tracking_and_persistence(monkeypatch):
    init_all_databases()
    monkeypatch.setenv("LLM_PRICE_INPUT_PER_1M", "1.0")
    monkeypatch.setenv("LLM_PRICE_OUTPUT_PER_1M", "2.0")
    monkeypatch.setenv("LLM_MAX_COST_PER_CALL_USD", "0")
    monkeypatch.setenv("LLM_MAX_LATENCY_MS", "0")
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "0")

    fake_client = _FakeClient(
        [
            _FakeResponse(
                model="deep-model",
                content="ok",
                prompt_tokens=1000,
                completion_tokens=500,
            )
        ]
    )
    client = UnifiedLLMClient(
        config=LLMConfig(base_url="https://api.test", api_key="k", model="deep-model"),
        client=fake_client,
    )
    session_id = f"sess-{uuid.uuid4().hex[:8]}"

    text, usage = asyncio.run(
        client.chat(
            [{"role": "user", "content": "hello"}],
            session_id=session_id,
            agent_id="unit-agent",
        )
    )

    assert text == "ok"
    # 1000/1e6*1 + 500/1e6*2 = 0.002
    assert abs(usage.cost_usd - 0.002) < 1e-9

    summary = TradingLedger.get_llm_usage_summary(hours=24, session_id=session_id)
    assert summary["call_count"] == 1
    assert summary["total_tokens"] == 1500
    assert summary["cost_usd"] == 0.002


def test_llm_governance_degrade_switch_to_quick_model(monkeypatch):
    init_all_databases()
    monkeypatch.setenv("LLM_PRICE_INPUT_PER_1M", "10.0")
    monkeypatch.setenv("LLM_PRICE_OUTPUT_PER_1M", "0")
    monkeypatch.setenv("LLM_MAX_COST_PER_CALL_USD", "0.001")
    monkeypatch.setenv("LLM_MAX_LATENCY_MS", "0")
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "0")
    monkeypatch.setenv("LLM_GOVERN_DEGRADE_ENABLED", "true")
    monkeypatch.setenv("LLM_QUICK_MODEL", "quick-model")

    fake_client = _FakeClient(
        [
            _FakeResponse(model="deep-model", content="first", prompt_tokens=500, completion_tokens=0),
            _FakeResponse(model="quick-model", content="second", prompt_tokens=10, completion_tokens=0),
        ]
    )
    client = UnifiedLLMClient(
        config=LLMConfig(base_url="https://api.test", api_key="k", model="deep-model"),
        client=fake_client,
    )

    _, usage1 = asyncio.run(client.chat([{"role": "user", "content": "one"}]))
    _, usage2 = asyncio.run(client.chat([{"role": "user", "content": "two"}]))

    assert "cost_per_call_exceeded" in usage1.governance_flags
    assert usage2.degraded is True
    assert fake_client.completions.calls[0]["model"] == "deep-model"
    assert fake_client.completions.calls[1]["model"] == "quick-model"


def test_llm_retry_recovers_from_error(monkeypatch):
    init_all_databases()
    monkeypatch.setenv("LLM_MAX_RETRIES", "1")
    monkeypatch.setenv("LLM_RETRY_BACKOFF_MS", "0")
    monkeypatch.setenv("LLM_REQUEST_TIMEOUT_S", "5")
    monkeypatch.setenv("LLM_GOVERN_DEGRADE_ENABLED", "false")

    fake_client = _FakeClient(
        [
            RuntimeError("transient"),
            _FakeResponse(model="deep-model", content="ok-after-retry", prompt_tokens=10, completion_tokens=10),
        ]
    )
    client = UnifiedLLMClient(
        config=LLMConfig(base_url="https://api.test", api_key="k", model="deep-model"),
        client=fake_client,
    )

    text, usage = asyncio.run(client.chat([{"role": "user", "content": "retry"}]))
    assert text == "ok-after-retry"
    assert "retried_1" in usage.governance_flags
    assert "error_recovered" in usage.governance_flags
    assert len(fake_client.completions.calls) == 2


def test_llm_fallback_to_quick_model_on_primary_failure(monkeypatch):
    init_all_databases()
    monkeypatch.setenv("LLM_MAX_RETRIES", "0")
    monkeypatch.setenv("LLM_RETRY_BACKOFF_MS", "0")
    monkeypatch.setenv("LLM_GOVERN_DEGRADE_ENABLED", "true")
    monkeypatch.setenv("LLM_QUICK_MODEL", "quick-model")

    fake_client = _FakeClient(
        [
            RuntimeError("deep-failed"),
            _FakeResponse(model="quick-model", content="quick-recovered", prompt_tokens=20, completion_tokens=5),
        ]
    )
    client = UnifiedLLMClient(
        config=LLMConfig(base_url="https://api.test", api_key="k", model="deep-model"),
        client=fake_client,
    )

    text, usage = asyncio.run(client.chat([{"role": "user", "content": "fallback"}]))
    assert text == "quick-recovered"
    assert usage.degraded is True
    assert "fallback_to_quick_model" in usage.governance_flags
    assert fake_client.completions.calls[0]["model"] == "deep-model"
    assert fake_client.completions.calls[1]["model"] == "quick-model"
