"""
Unified OpenAI-compatible LLM client with governance and cost tracking.
"""
from __future__ import annotations

import asyncio
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI
from src.core.cost_tracker import CostTracker
from src.llm.config_provider import llm_config_provider


@dataclass
class LLMUsage:
    """Single call usage metrics."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    model: str = ""
    provider: str = ""
    session_id: str = ""
    agent_id: str = ""
    governance_flags: list[str] = field(default_factory=list)
    degraded: bool = False


@dataclass
class LLMConfig:
    """OpenAI-compatible endpoint config."""

    base_url: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout: float = 120.0

    @classmethod
    def from_env(cls, prefix: str = "LLM") -> "LLMConfig":
        return cls(
            base_url=_config_value(f"{prefix}_BASE_URL", "https://api.deepseek.com"),
            api_key=_config_value(f"{prefix}_API_KEY", ""),
            model=_config_value(f"{prefix}_MODEL", "deepseek-chat"),
            timeout=_to_positive_float(_config_value(f"{prefix}_REQUEST_TIMEOUT_S", "120"), default=120.0),
        )

    @classmethod
    def deep_think(cls) -> "LLMConfig":
        cfg = cls.from_env()
        deep_model = _config_value("LLM_DEEP_MODEL", "")
        if deep_model:
            cfg.model = deep_model
        cfg.temperature = 0.3
        cfg.max_tokens = 8192
        return cfg

    @classmethod
    def quick_think(cls) -> "LLMConfig":
        cfg = cls.from_env()
        quick_model = _config_value("LLM_QUICK_MODEL", "")
        if quick_model:
            cfg.model = quick_model
        cfg.temperature = 0.5
        cfg.max_tokens = 2048
        return cfg


_RUNTIME_LOCK = threading.RLock()
_CONFIG_LOCK = threading.RLock()
_RUNTIME_CONFIG_OVERRIDES: dict[str, str] = {}
_RUNTIME_METRICS: dict[str, Any] = {
    "call_count": 0,
    "total_input_tokens": 0,
    "total_output_tokens": 0,
    "total_cost_usd": 0.0,
    "latency_exceeded_count": 0,
    "cost_exceeded_count": 0,
    "budget_exceeded_count": 0,
    "degrade_switch_count": 0,
    "retry_recovered_count": 0,
    "timeout_recovered_count": 0,
    "error_recovered_count": 0,
    "fallback_quick_count": 0,
    "last_call_ts": 0.0,
    "last_flags": [],
}

_CONFIG_KEYS = (
    "LLM_PROVIDER_NAME",
    "LLM_BASE_URL",
    "LLM_API_KEY",
    "LLM_MODEL",
    "LLM_QUICK_MODEL",
    "LLM_DEEP_MODEL",
    "LLM_REQUEST_TIMEOUT_S",
    "LLM_MAX_TOKENS",
    "LLM_TEMPERATURE",
)
_COST_TRACKER = CostTracker()


def _config_value(name: str, default: str = "") -> str:
    with _CONFIG_LOCK:
        if name in _RUNTIME_CONFIG_OVERRIDES:
            return str(_RUNTIME_CONFIG_OVERRIDES[name])
    return str(os.getenv(name, default))


def _to_positive_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    return number if number > 0 else float(default)


def _to_non_negative_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    return number if number >= 0 else float(default)


def _to_positive_int(value: Any, default: int = 1) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return int(default)
    return number if number > 0 else int(default)


def _mask_api_key(api_key: str) -> str:
    key = str(api_key or "")
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}***{key[-4:]}"


def apply_llm_runtime_config(config: dict[str, Any], *, persist_env: bool = True) -> dict[str, Any]:
    """
    Apply runtime overrides for LLM config.
    """
    updates = {
        "LLM_PROVIDER_NAME": str(config.get("provider_name") or "").strip(),
        "LLM_BASE_URL": str(config.get("base_url") or "").strip(),
        "LLM_MODEL": str(config.get("model") or "").strip(),
        "LLM_QUICK_MODEL": str(config.get("quick_model") or "").strip(),
        "LLM_DEEP_MODEL": str(config.get("deep_model") or "").strip(),
        "LLM_REQUEST_TIMEOUT_S": str(config.get("timeout_s") or "").strip(),
        "LLM_MAX_TOKENS": str(config.get("max_tokens") or "").strip(),
        "LLM_TEMPERATURE": str(config.get("temperature") or "").strip(),
    }
    api_key = str(config.get("api_key") or "").strip()
    if api_key:
        updates["LLM_API_KEY"] = api_key

    with _CONFIG_LOCK:
        for key, value in updates.items():
            if value == "":
                continue
            _RUNTIME_CONFIG_OVERRIDES[key] = value
            if persist_env:
                os.environ[key] = value
        if api_key and persist_env:
            os.environ["LLM_API_KEY"] = api_key
            _RUNTIME_CONFIG_OVERRIDES["LLM_API_KEY"] = api_key

    return get_llm_effective_config()


def get_llm_effective_config() -> dict[str, Any]:
    with _CONFIG_LOCK:
        data = {key: _config_value(key, "") for key in _CONFIG_KEYS}
    timeout_s = _to_positive_float(data.get("LLM_REQUEST_TIMEOUT_S", "120"), default=120.0)
    max_tokens = _to_positive_int(data.get("LLM_MAX_TOKENS", "4096"), default=4096)
    temperature = _to_non_negative_float(data.get("LLM_TEMPERATURE", "0.7"), default=0.7)
    return {
        "provider_name": str(data.get("LLM_PROVIDER_NAME", "") or "").strip() or "custom",
        "base_url": str(data.get("LLM_BASE_URL", "") or "").strip(),
        "model": str(data.get("LLM_MODEL", "") or "").strip(),
        "quick_model": str(data.get("LLM_QUICK_MODEL", "") or "").strip(),
        "deep_model": str(data.get("LLM_DEEP_MODEL", "") or "").strip(),
        "timeout_s": timeout_s,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "has_api_key": bool(str(data.get("LLM_API_KEY", "") or "").strip()),
        "api_key_masked": _mask_api_key(str(data.get("LLM_API_KEY", "") or "").strip()),
        "source": "runtime_override" if bool(_RUNTIME_CONFIG_OVERRIDES) else "env",
    }


def _runtime_mark(usage: LLMUsage) -> None:
    with _RUNTIME_LOCK:
        _RUNTIME_METRICS["call_count"] += 1
        _RUNTIME_METRICS["total_input_tokens"] += int(usage.input_tokens)
        _RUNTIME_METRICS["total_output_tokens"] += int(usage.output_tokens)
        _RUNTIME_METRICS["total_cost_usd"] += float(usage.cost_usd)
        _RUNTIME_METRICS["last_call_ts"] = time.time()
        _RUNTIME_METRICS["last_flags"] = list(usage.governance_flags)
        if "latency_exceeded" in usage.governance_flags:
            _RUNTIME_METRICS["latency_exceeded_count"] += 1
        if "cost_per_call_exceeded" in usage.governance_flags:
            _RUNTIME_METRICS["cost_exceeded_count"] += 1
        if "daily_budget_exceeded" in usage.governance_flags:
            _RUNTIME_METRICS["budget_exceeded_count"] += 1
        if usage.degraded:
            _RUNTIME_METRICS["degrade_switch_count"] += 1
        if any(flag.startswith("retried_") for flag in usage.governance_flags):
            _RUNTIME_METRICS["retry_recovered_count"] += 1
        if "timeout_recovered" in usage.governance_flags:
            _RUNTIME_METRICS["timeout_recovered_count"] += 1
        if "error_recovered" in usage.governance_flags:
            _RUNTIME_METRICS["error_recovered_count"] += 1
        if "fallback_to_quick_model" in usage.governance_flags:
            _RUNTIME_METRICS["fallback_quick_count"] += 1


def get_llm_runtime_metrics() -> dict[str, Any]:
    with _RUNTIME_LOCK:
        call_count = int(_RUNTIME_METRICS["call_count"])
        total_input = int(_RUNTIME_METRICS["total_input_tokens"])
        total_output = int(_RUNTIME_METRICS["total_output_tokens"])
        avg_tokens = (total_input + total_output) / call_count if call_count else 0.0
        return {
            "call_count": call_count,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_cost_usd": round(float(_RUNTIME_METRICS["total_cost_usd"]), 6),
            "avg_tokens_per_call": round(avg_tokens, 2),
            "latency_exceeded_count": int(_RUNTIME_METRICS["latency_exceeded_count"]),
            "cost_exceeded_count": int(_RUNTIME_METRICS["cost_exceeded_count"]),
            "budget_exceeded_count": int(_RUNTIME_METRICS["budget_exceeded_count"]),
            "degrade_switch_count": int(_RUNTIME_METRICS["degrade_switch_count"]),
            "retry_recovered_count": int(_RUNTIME_METRICS["retry_recovered_count"]),
            "timeout_recovered_count": int(_RUNTIME_METRICS["timeout_recovered_count"]),
            "error_recovered_count": int(_RUNTIME_METRICS["error_recovered_count"]),
            "fallback_quick_count": int(_RUNTIME_METRICS["fallback_quick_count"]),
            "last_call_ts": float(_RUNTIME_METRICS["last_call_ts"]),
            "last_flags": list(_RUNTIME_METRICS["last_flags"]),
        }


class UnifiedLLMClient:
    """
    Unified LLM client for OpenAI-compatible providers.
    Supports lightweight cost/latency governance and runtime degradation.
    """

    def __init__(self, config: LLMConfig | None = None, client: Any | None = None):
        # T-42: 动态读取单例配置
        runtime_cfg = llm_config_provider.get_config()
        self.config = config or LLMConfig(
            base_url=runtime_cfg.base_url,
            api_key=runtime_cfg.api_key,
            model=runtime_cfg.model,
            temperature=runtime_cfg.temperature,
            max_tokens=runtime_cfg.max_tokens,
            timeout=runtime_cfg.timeout_s
        )
        self._client = client or AsyncOpenAI(
            base_url=self.config.base_url,
            api_key=self.config.api_key,
            timeout=self.config.timeout,
        )
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._total_cost_usd = 0.0
        self._call_count = 0
        self._degrade_mode = False
        self._governance = {
            "price_input_per_1m": _env_float("LLM_PRICE_INPUT_PER_1M", 0.0),
            "price_output_per_1m": _env_float("LLM_PRICE_OUTPUT_PER_1M", 0.0),
            "max_latency_ms": _env_float("LLM_MAX_LATENCY_MS", 0.0),
            "max_cost_per_call": _env_float("LLM_MAX_COST_PER_CALL_USD", 0.0),
            "daily_budget_usd": _env_float("LLM_DAILY_BUDGET_USD", 0.0),
            "degrade_enabled": _config_value("LLM_GOVERN_DEGRADE_ENABLED", "true").lower() == "true",
            "quick_model": _config_value("LLM_QUICK_MODEL", "").strip(),
            "request_timeout_s": _env_float("LLM_REQUEST_TIMEOUT_S", self.config.timeout),
            "max_retries": _env_int("LLM_MAX_RETRIES", 1),
            "retry_backoff_ms": _env_float("LLM_RETRY_BACKOFF_MS", 200.0),
        }

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        *,
        session_id: str = "",
        agent_id: str = "",
        **kwargs: Any,
    ) -> tuple[str, LLMUsage]:
        start = time.monotonic()
        requested_model = model or self.config.model
        selected_model = requested_model
        pre_flags: list[str] = []

        if self._degrade_mode and self._governance["degrade_enabled"]:
            quick_model = str(self._governance["quick_model"] or "").strip()
            if quick_model and quick_model != requested_model:
                selected_model = quick_model
                pre_flags.append("degraded_to_quick_model")

        request_payload: dict[str, Any] = {
            "model": selected_model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.config.temperature,
            "max_tokens": max_tokens or self.config.max_tokens,
            **kwargs,
        }
        call_flags: list[str] = []
        try:
            response, retry_flags = await self._request_with_retry(request_payload)
            call_flags.extend(retry_flags)
        except Exception as primary_exc:
            quick_model = str(self._governance["quick_model"] or "").strip()
            can_fallback = (
                self._governance["degrade_enabled"]
                and quick_model
                and quick_model != selected_model
            )
            if not can_fallback:
                raise

            fallback_payload = dict(request_payload)
            fallback_payload["model"] = quick_model
            response, retry_flags = await self._request_with_retry(fallback_payload)
            selected_model = quick_model
            pre_flags.extend(["fallback_to_quick_model", "degraded_to_quick_model"])
            call_flags.extend(retry_flags)
            # Keep original error context in case downstream auditing needs it.
            _ = primary_exc

        elapsed_ms = (time.monotonic() - start) * 1000
        prompt_tokens = int(getattr(getattr(response, "usage", None), "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(getattr(response, "usage", None), "completion_tokens", 0) or 0)
        total_tokens = int(getattr(getattr(response, "usage", None), "total_tokens", 0) or 0)
        if total_tokens <= 0:
            total_tokens = prompt_tokens + completion_tokens

        usage = LLMUsage(
            input_tokens=prompt_tokens,
            output_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=elapsed_ms,
            model=str(getattr(response, "model", "") or selected_model),
            provider=self.config.base_url,
            session_id=session_id,
            agent_id=agent_id,
            governance_flags=list(pre_flags) + call_flags,
            degraded=bool(pre_flags),
        )
        usage.cost_usd = self._estimate_cost_usd(prompt_tokens, completion_tokens)

        usage_flags = self._evaluate_governance_flags(usage)
        if usage_flags:
            usage.governance_flags.extend(usage_flags)
        usage.degraded = usage.degraded or any(
            flag in usage.governance_flags
            for flag in ("degraded_to_quick_model", "fallback_to_quick_model")
        )

        self._total_input_tokens += usage.input_tokens
        self._total_output_tokens += usage.output_tokens
        self._total_cost_usd += usage.cost_usd
        self._call_count += 1
        _runtime_mark(usage)
        self._persist_usage(usage)

        content = ""
        choices = getattr(response, "choices", None) or []
        if choices:
            content = getattr(getattr(choices[0], "message", None), "content", "") or ""
        return content, usage

    async def chat_simple(
        self,
        prompt: str,
        system: str = "",
        *,
        session_id: str = "",
        agent_id: str = "",
    ) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        text, _ = await self.chat(messages, session_id=session_id, agent_id=agent_id)
        return text

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "call_count": self._call_count,
            "total_input_tokens": self._total_input_tokens,
            "total_output_tokens": self._total_output_tokens,
            "total_cost_usd": round(self._total_cost_usd, 6),
            "degrade_mode": self._degrade_mode,
        }

    def _estimate_cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        input_rate = float(self._governance["price_input_per_1m"])
        output_rate = float(self._governance["price_output_per_1m"])
        if input_rate <= 0 and output_rate <= 0:
            return 0.0
        input_cost = (max(0, int(input_tokens)) / 1_000_000.0) * max(0.0, input_rate)
        output_cost = (max(0, int(output_tokens)) / 1_000_000.0) * max(0.0, output_rate)
        return round(input_cost + output_cost, 8)

    def _evaluate_governance_flags(self, usage: LLMUsage) -> list[str]:
        flags: list[str] = []
        max_latency_ms = float(self._governance["max_latency_ms"])
        max_cost_per_call = float(self._governance["max_cost_per_call"])
        daily_budget = float(self._governance["daily_budget_usd"])

        if max_latency_ms > 0 and usage.latency_ms > max_latency_ms:
            flags.append("latency_exceeded")
        if max_cost_per_call > 0 and usage.cost_usd > max_cost_per_call:
            flags.append("cost_per_call_exceeded")
        if daily_budget > 0 and self._is_daily_budget_exceeded(usage.cost_usd, daily_budget):
            flags.append("daily_budget_exceeded")

        if flags and self._governance["degrade_enabled"]:
            self._degrade_mode = True
        return flags

    def _is_daily_budget_exceeded(self, current_call_cost: float, daily_budget: float) -> bool:
        try:
            status = _COST_TRACKER.daily_budget_status(
                daily_budget_usd=daily_budget,
                current_call_cost=current_call_cost,
                hours=24,
            )
            return bool(status.get("exceeded", False))
        except Exception:
            return False

    def _persist_usage(self, usage: LLMUsage) -> None:
        try:
            _COST_TRACKER.record_usage(
                {
                    "id": str(uuid.uuid4()),
                    "timestamp": time.time(),
                    "provider": usage.provider,
                    "model": usage.model,
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "cost_usd": usage.cost_usd,
                    "agent_id": usage.agent_id,
                    "session_id": usage.session_id,
                    "latency_ms": usage.latency_ms,
                    "governance_flags": usage.governance_flags,
                    "degraded": usage.degraded,
                }
            )
        except Exception:
            # Persistence failure should not break trading flow.
            return

    async def _request_with_retry(self, payload: dict[str, Any]) -> tuple[Any, list[str]]:
        timeout_s = max(0.1, float(self._governance["request_timeout_s"]))
        max_retries = max(0, int(self._governance["max_retries"]))
        backoff_ms = max(0.0, float(self._governance["retry_backoff_ms"]))

        retries_used = 0
        recovered_timeout = False
        recovered_error = False
        last_exc: Exception | None = None

        for attempt in range(max_retries + 1):
            try:
                response = await asyncio.wait_for(
                    self._client.chat.completions.create(**payload),
                    timeout=timeout_s,
                )
                flags: list[str] = []
                if retries_used > 0:
                    flags.append(f"retried_{retries_used}")
                if recovered_timeout:
                    flags.append("timeout_recovered")
                if recovered_error:
                    flags.append("error_recovered")
                return response, flags
            except asyncio.TimeoutError as exc:
                last_exc = exc
                recovered_timeout = True
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                recovered_error = True

            if attempt >= max_retries:
                break

            retries_used += 1
            sleep_s = (backoff_ms / 1000.0) * (2**attempt)
            if sleep_s > 0:
                await asyncio.sleep(min(sleep_s, 5.0))

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("LLM request failed without explicit exception")


def create_llm(config: LLMConfig | None = None) -> UnifiedLLMClient:
    return UnifiedLLMClient(config)


def create_deep_llm() -> UnifiedLLMClient:
    return UnifiedLLMClient(LLMConfig.deep_think())


def create_quick_llm() -> UnifiedLLMClient:
    return UnifiedLLMClient(LLMConfig.quick_think())


def _env_float(name: str, default: float) -> float:
    raw = _config_value(name, "")
    if raw == "":
        return float(default)
    try:
        return float(raw)
    except ValueError:
        return float(default)


def _env_int(name: str, default: int) -> int:
    raw = _config_value(name, "")
    if raw == "":
        return int(default)
    try:
        return int(raw)
    except ValueError:
        return int(default)
