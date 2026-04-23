import json
import os
import sys
import threading
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class LLMRuntimeConfig(BaseModel):
    provider_name: str = Field(default="custom", description="LLM provider name")
    base_url: str = Field(default="https://api.deepseek.com", description="OpenAI compatible base_url")
    api_key: str = Field(default="", description="API key")
    model: str = Field(default="deepseek-chat", description="Default model name")
    quick_model: str = Field(default="", description="Quick model name")
    deep_model: str = Field(default="", description="Deep model name")
    timeout_s: float = Field(default=120.0, gt=0, description="Request timeout in seconds")
    max_tokens: int = Field(default=4096, ge=1, description="Default max tokens")
    temperature: float = Field(default=0.7, ge=0, le=2, description="Default sampling temperature")


class LLMConfigurationProvider:
    """LLM runtime config singleton provider."""

    _instance: Optional["LLMConfigurationProvider"] = None
    _lock = threading.RLock()
    _config: LLMRuntimeConfig
    _config_filename = "llm_runtime.json"

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init_config()
            return cls._instance

    @property
    def _config_path(self) -> str:
        """Resolve config file path with fallback for packaged/runtime env."""
        try:
            if hasattr(sys, "_MEIPASS"):
                base_dir = os.path.dirname(sys.executable)
            else:
                base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                if not os.path.exists(os.path.join(base_dir, "pyproject.toml")):
                    base_dir = os.getcwd()

            config_dir = os.path.join(base_dir, "config")
            if not os.path.exists(config_dir):
                try:
                    os.makedirs(config_dir, exist_ok=True)
                except OSError:
                    if os.name == "nt":
                        appdata_dir = os.path.join(os.getenv("APPDATA", ""), "AttractWealth", "config")
                        os.makedirs(appdata_dir, exist_ok=True)
                        return os.path.join(appdata_dir, self._config_filename)
                    raise

            return os.path.join(config_dir, self._config_filename)
        except Exception as exc:  # noqa: BLE001
            fallback_path = os.path.join(os.getcwd(), "config", self._config_filename)
            print(f"Path resolution warning: {exc}. Falling back to: {fallback_path}")
            return fallback_path

    def _init_config(self):
        """Initialize config from env defaults and local runtime file."""
        data = {
            "provider_name": os.getenv("LLM_PROVIDER_NAME", "custom"),
            "base_url": os.getenv("LLM_BASE_URL", "https://api.deepseek.com"),
            "api_key": os.getenv("LLM_API_KEY", ""),
            "model": os.getenv("LLM_MODEL", "deepseek-chat"),
            "quick_model": os.getenv("LLM_QUICK_MODEL", ""),
            "deep_model": os.getenv("LLM_DEEP_MODEL", ""),
            "timeout_s": float(os.getenv("LLM_REQUEST_TIMEOUT_S", "120")),
            "max_tokens": int(os.getenv("LLM_MAX_TOKENS", "4096")),
            "temperature": float(os.getenv("LLM_TEMPERATURE", "0.7")),
        }

        if os.path.exists(self._config_path):
            try:
                with open(self._config_path, "r", encoding="utf-8") as f:
                    file_data = json.load(f)
                if isinstance(file_data, dict):
                    data.update(file_data)
            except Exception as exc:  # noqa: BLE001
                print(f"Failed to load LLM config from {self._config_path}: {exc}")

        self._config = LLMRuntimeConfig(**data)
        self._sync_to_env(self._config.model_dump())

    def get_config(self) -> LLMRuntimeConfig:
        with self._lock:
            return self._config

    def update_config(self, **kwargs) -> LLMRuntimeConfig:
        """Update in-memory config and persist to local runtime file."""
        with self._lock:
            updates = {
                k: v
                for k, v in kwargs.items()
                if v is not None and not (isinstance(v, str) and ("*" in v or "••" in v))
            }

            current_data = self._config.model_dump()
            current_data.update(updates)

            self._config = LLMRuntimeConfig(**current_data)
            self._save_to_file()
            self._sync_to_env(updates)
            return self._config

    def _save_to_file(self):
        """Persist current config to JSON file."""
        try:
            os.makedirs(os.path.dirname(self._config_path), exist_ok=True)
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(self._config.model_dump(), f, indent=4, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            print(f"Failed to save LLM config to {self._config_path}: {exc}")

    def _sync_to_env(self, updates: Dict[str, Any]):
        mapping = {
            "provider_name": "LLM_PROVIDER_NAME",
            "base_url": "LLM_BASE_URL",
            "api_key": "LLM_API_KEY",
            "model": "LLM_MODEL",
            "quick_model": "LLM_QUICK_MODEL",
            "deep_model": "LLM_DEEP_MODEL",
            "timeout_s": "LLM_REQUEST_TIMEOUT_S",
            "max_tokens": "LLM_MAX_TOKENS",
            "temperature": "LLM_TEMPERATURE",
        }
        for key, env_key in mapping.items():
            if key in updates:
                os.environ[env_key] = str(updates[key])


llm_config_provider = LLMConfigurationProvider()
