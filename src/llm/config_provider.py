import os
import sys
import threading
import json
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

class LLMRuntimeConfig(BaseModel):
    provider_name: str = Field(default="custom", description="LLM 供应商名称")
    base_url: str = Field(default="https://api.deepseek.com", description="OpenAI 兼容 base_url")
    api_key: str = Field(default="", description="API key")
    model: str = Field(default="deepseek-chat", description="默认模型名称")
    quick_model: str = Field(default="", description="快速模型名称")
    deep_model: str = Field(default="", description="深度模型名称")
    timeout_s: float = Field(default=120.0, gt=0, description="请求超时秒数")
    max_tokens: int = Field(default=4096, ge=1, description="默认 max_tokens")
    temperature: float = Field(default=0.7, ge=0, le=2, description="默认 temperature")

class LLMConfigurationProvider:
    """LLM 配置单例管理器 (T-42)"""
    _instance: Optional['LLMConfigurationProvider'] = None
    _lock = threading.RLock()
    _config: LLMRuntimeConfig
    
    # 修复：使用绝对路径，基于项目根目录 (pyproject.toml 所在位置)
    _config_filename = "llm_runtime.json"

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(LLMConfigurationProvider, cls).__new__(cls)
                cls._instance._init_config()
            return cls._instance

    @property
    def _config_path(self) -> str:
        """动态计算配置文件的绝对路径 (工业级兼容逻辑)"""
        try:
            # 1. 核心目录定位逻辑
            if hasattr(sys, '_MEIPASS'):
                # PyInstaller 运行环境: 必须保存在 EXE 同级的 config 目录下 (绿色版逻辑)
                # sys.executable 是 EXE 的完整路径
                base_dir = os.path.dirname(sys.executable)
            else:
                # 开发环境: 基于项目根目录 (pyproject.toml 所在位置)
                # src/llm/config_provider.py -> src/llm -> src -> Root
                base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                # 兼容性检查：若 root_dir 找不到标识文件，使用当前工作目录
                if not os.path.exists(os.path.join(base_dir, 'pyproject.toml')):
                    base_dir = os.getcwd()

            config_dir = os.path.join(base_dir, 'config')
            
            # 2. 权限与目录创建校验
            if not os.path.exists(config_dir):
                try:
                    os.makedirs(config_dir, exist_ok=True)
                except OSError as e:
                    # 如果当前目录不可写 (如 C:\Program Files)，尝试备选路径 %APPDATA%
                    if os.name == 'nt':
                        appdata_dir = os.path.join(os.getenv('APPDATA', ''), 'AttractWealth', 'config')
                        os.makedirs(appdata_dir, exist_ok=True)
                        return os.path.join(appdata_dir, self._config_filename)
                    raise e
            
            return os.path.join(config_dir, self._config_filename)
        except Exception as e:
            # 最后的兜底策略：使用当前目录下的 config
            fallback_path = os.path.join(os.getcwd(), 'config', self._config_filename)
            print(f"Path resolution warning: {e}. Falling back to: {fallback_path}")
            return fallback_path

    def _init_config(self):
        """初始加载：文件优先，其次环境变量，最后默认值"""
        # 1. 默认值与环境变量
        data = {
            "provider_name": os.getenv("LLM_PROVIDER_NAME", "custom"),
            "base_url": os.getenv("LLM_BASE_URL", "https://api.deepseek.com"),
            "api_key": os.getenv("LLM_API_KEY", ""),
            "model": os.getenv("LLM_MODEL", "deepseek-chat"),
            "quick_model": os.getenv("LLM_QUICK_MODEL", ""),
            "deep_model": os.getenv("LLM_DEEP_MODEL", ""),
            "timeout_s": float(os.getenv("LLM_REQUEST_TIMEOUT_S", "120")),
            "max_tokens": int(os.getenv("LLM_MAX_TOKENS", "4096")),
            "temperature": float(os.getenv("LLM_TEMPERATURE", "0.7"))
        }

        # 2. 从文件加载覆盖
        if os.path.exists(self._config_path):
            try:
                with open(self._config_path, 'r', encoding='utf-8') as f:
                    file_data = json.load(f)
                    data.update(file_data)
            except Exception as e:
                print(f"Failed to load LLM config from {self._config_path}: {e}")

        self._config = LLMRuntimeConfig(**data)
        # 初始化时同步一次环境变量
        self._sync_to_env(self._config.dict())

    def get_config(self) -> LLMRuntimeConfig:
        with self._lock:
            return self._config

    def update_config(self, **kwargs) -> LLMRuntimeConfig:
        """更新内存中的配置并持久化到文件"""
        with self._lock:
            # 过滤掉 None 值，且过滤掩码值 (•••• 或 sk-a***1234)
            # 工业级设计：如果传入的值包含掩码字符，视为用户未修改，不更新
            updates = {
                k: v for k, v in kwargs.items() 
                if v is not None and not (isinstance(v, str) and ("•" in v or "*" in v))
            }
            
            current_data = self._config.dict()
            current_data.update(updates)
            
            # 使用 pydantic 重新校验
            new_config = LLMRuntimeConfig(**current_data)
            self._config = new_config
            
            # 持久化到文件
            self._save_to_file()
            
            # 同步更新环境变量以兼容旧的 os.getenv 调用
            self._sync_to_env(updates)
            return self._config

    def _save_to_file(self):
        """将当前配置写入 JSON 文件"""
        try:
            os.makedirs(os.path.dirname(self._config_path), exist_ok=True)
            with open(self._config_path, 'w', encoding='utf-8') as f:
                json.dump(self._config.dict(), f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Failed to save LLM config to {self._config_path}: {e}")

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
            "temperature": "LLM_TEMPERATURE"
        }
        for key, env_key in mapping.items():
            if key in updates:
                os.environ[env_key] = str(updates[key])

# 全局单例
llm_config_provider = LLMConfigurationProvider()
