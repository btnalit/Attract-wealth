"""
来财 (Attract-wealth) — 配置守护层
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import toml
from pydantic import BaseModel, ConfigDict
from pydantic_settings import BaseSettings

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"

class ProviderConfig(BaseModel):
    base_url: str = ""
    model: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096


class LLMConfigManager:
    """LLM 配置管理器，从 toml 加载"""
    def __init__(self):
        self.config_path = CONFIG_DIR / "llm_providers.toml"
        self._raw_config: Dict[str, Any] = {}
        self.load()

    def load(self):
        if self.config_path.exists():
            with open(self.config_path, "r", encoding="utf-8") as f:
                self._raw_config = toml.load(f)

    def get_provider_config(self, provider_name: str = "default") -> ProviderConfig:
        config_data = self._raw_config.get(provider_name, {})
        if not config_data and provider_name != "default":
            # 回退到 default
            config_data = self._raw_config.get("default", {})
        return ProviderConfig(**config_data)


# 全局 LLM 配置单例
llm_config_manager = LLMConfigManager()


class AppSettings(BaseSettings):
    """应用全局环境变量配置"""
    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    env: str = "dev"
    data_dir: str = str(PROJECT_ROOT / "data")
    
    # LLM
    llm_provider: str = "default"
    llm_api_key: str = ""
    
    # 第三方数据源 Token
    tushare_token: str = ""
    
    # HTTP 服务
    host: str = "0.0.0.0"
    port: int = 8000


settings = AppSettings()
