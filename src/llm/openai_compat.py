"""
来财 LLM 层 — 基于 OpenAI 兼容协议的统一 LLM 客户端

所有 Provider (DeepSeek/Qwen/Kimi/OpenAI/Ollama/SiliconFlow) 统一使用
OpenAI Python SDK 的 `/v1/chat/completions` 接口调用。
通过 base_url + api_key + model 三元组切换。
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI


@dataclass
class LLMUsage:
    """单次调用的 token 用量与成本"""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    model: str = ""
    provider: str = ""


@dataclass
class LLMConfig:
    """LLM 连接配置"""
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout: float = 120.0

    @classmethod
    def from_env(cls, prefix: str = "LLM") -> "LLMConfig":
        """从环境变量加载配置"""
        return cls(
            base_url=os.getenv(f"{prefix}_BASE_URL", "https://api.deepseek.com"),
            api_key=os.getenv(f"{prefix}_API_KEY", ""),
            model=os.getenv(f"{prefix}_MODEL", "deepseek-chat"),
        )

    @classmethod
    def deep_think(cls) -> "LLMConfig":
        """深度思考模型配置 (复杂分析用)"""
        cfg = cls.from_env()
        deep_model = os.getenv("LLM_DEEP_MODEL", "")
        if deep_model:
            cfg.model = deep_model
        cfg.temperature = 0.3
        cfg.max_tokens = 8192
        return cfg

    @classmethod
    def quick_think(cls) -> "LLMConfig":
        """快速思考模型配置 (简单任务用)"""
        cfg = cls.from_env()
        quick_model = os.getenv("LLM_QUICK_MODEL", "")
        if quick_model:
            cfg.model = quick_model
        cfg.temperature = 0.5
        cfg.max_tokens = 2048
        return cfg


class UnifiedLLMClient:
    """
    统一 LLM 客户端 — 所有 Provider 通过 OpenAI 兼容协议调用

    支持的 Provider (仅需配置 base_url):
    - DeepSeek:     https://api.deepseek.com
    - Qwen:         https://dashscope.aliyuncs.com/compatible-mode/v1
    - Kimi:         https://api.moonshot.cn/v1
    - OpenAI:       https://api.openai.com/v1
    - Ollama:       http://localhost:11434/v1
    - SiliconFlow:  https://api.siliconflow.cn/v1
    - OpenRouter:   https://openrouter.ai/api/v1
    """

    def __init__(self, config: LLMConfig | None = None):
        self.config = config or LLMConfig.from_env()
        self._client = AsyncOpenAI(
            base_url=self.config.base_url,
            api_key=self.config.api_key,
            timeout=self.config.timeout,
        )
        # 累计成本追踪
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._total_cost_usd = 0.0
        self._call_count = 0

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> tuple[str, LLMUsage]:
        """
        发送 chat completion 请求

        Returns:
            (response_text, usage) 元组
        """
        start = time.monotonic()

        response = await self._client.chat.completions.create(
            model=model or self.config.model,
            messages=messages,
            temperature=temperature if temperature is not None else self.config.temperature,
            max_tokens=max_tokens or self.config.max_tokens,
            **kwargs,
        )

        elapsed = (time.monotonic() - start) * 1000

        # 提取用量
        usage = LLMUsage(
            input_tokens=response.usage.prompt_tokens if response.usage else 0,
            output_tokens=response.usage.completion_tokens if response.usage else 0,
            total_tokens=response.usage.total_tokens if response.usage else 0,
            latency_ms=elapsed,
            model=response.model or self.config.model,
            provider=self.config.base_url,
        )

        # 累计
        self._total_input_tokens += usage.input_tokens
        self._total_output_tokens += usage.output_tokens
        self._call_count += 1

        content = response.choices[0].message.content or "" if response.choices else ""
        return content, usage

    async def chat_simple(self, prompt: str, system: str = "") -> str:
        """简单问答 — 只需 prompt, 返回文本"""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        text, _ = await self.chat(messages)
        return text

    @property
    def stats(self) -> dict:
        """累计调用统计"""
        return {
            "call_count": self._call_count,
            "total_input_tokens": self._total_input_tokens,
            "total_output_tokens": self._total_output_tokens,
            "total_cost_usd": self._total_cost_usd,
        }


# ============ 便捷工厂函数 ============

def create_llm(config: LLMConfig | None = None) -> UnifiedLLMClient:
    """创建默认 LLM 客户端"""
    return UnifiedLLMClient(config)

def create_deep_llm() -> UnifiedLLMClient:
    """创建深度思考 LLM (复杂分析)"""
    return UnifiedLLMClient(LLMConfig.deep_think())

def create_quick_llm() -> UnifiedLLMClient:
    """创建快速 LLM (简单任务)"""
    return UnifiedLLMClient(LLMConfig.quick_think())
