"""System config service for file-backed runtime settings and notification checks."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from src.channels.wechat import WeChatChannel


class SystemConfigService:
    """Service layer for system config and notification test endpoints."""

    def __init__(self, config_path: str | Path | None = None):
        self._config_path = Path(config_path).resolve() if config_path else self._resolve_default_config_path()

    @staticmethod
    def _resolve_default_config_path() -> Path:
        if hasattr(sys, "_MEIPASS"):
            base_dir = Path(sys.executable).resolve().parent
        else:
            base_dir = Path(__file__).resolve().parents[2]
            if not (base_dir / "pyproject.toml").exists():
                base_dir = Path.cwd()
        config_dir = base_dir / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / "system_runtime.json"

    def load_runtime_config(self) -> dict[str, Any]:
        """Load merged runtime config from env + file."""
        payload = {
            "tushare_token": os.getenv("TUSHARE_TOKEN", ""),
            "wechat_webhook": os.getenv("WECHAT_WEBHOOK_URL", ""),
            "dingtalk_secret": os.getenv("DINGTALK_SECRET", ""),
        }
        path = self._config_path
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    payload.update(loaded)
            except Exception:  # noqa: BLE001
                pass
        return payload

    def save_runtime_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """Persist runtime config patch to file and sync selected env vars."""
        current: dict[str, Any] = {}
        path = self._config_path
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    current = loaded
            except Exception:  # noqa: BLE001
                current = {}

        updates = {
            key: value
            for key, value in dict(config or {}).items()
            if value is not None and value != "" and "•" not in str(value)
        }
        current.update(updates)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(current, f, indent=4, ensure_ascii=False)

        if "wechat_webhook" in current:
            os.environ["WECHAT_WEBHOOK_URL"] = str(current["wechat_webhook"])
        if "tushare_token" in current:
            os.environ["TUSHARE_TOKEN"] = str(current["tushare_token"])
        if "dingtalk_secret" in current:
            os.environ["DINGTALK_SECRET"] = str(current["dingtalk_secret"])
        return current

    def send_wechat_test(self, webhook_url: str) -> bool:
        """Send test message to WeChat webhook channel."""
        channel = WeChatChannel(webhook_url=webhook_url)
        return bool(
            channel.send(
                title="🔔 系统通知测试",
                content=(
                    "这是来自来财 (Attract-wealth) 系统配置页面的连通性测试消息。\n\n"
                    f"**测试时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    "**状态**: 运行中"
                ),
                level="info",
            )
        )

