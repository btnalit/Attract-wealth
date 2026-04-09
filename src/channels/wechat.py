import os
import requests
import logging
from typing import Optional, Any
from .base import BaseChannel

logger = logging.getLogger(__name__)

class WeChatChannel(BaseChannel):
    """企业微信通知通道 (Webhook)"""
    
    def __init__(self, webhook_url: Optional[str] = None):
        self.webhook_url = webhook_url or os.getenv("WECHAT_WEBHOOK_URL")
        if not self.webhook_url:
            logger.warning("WECHAT_WEBHOOK_URL is not set.")
            
    def _post_with_retry(self, data: dict[str, Any], retries: int = 3) -> bool:
        if not self.webhook_url:
            logger.error("WeChat webhook URL not configured.")
            return False
        
        for i in range(retries):
            try:
                response = requests.post(self.webhook_url, json=data, timeout=10)
                response.raise_for_status()
                res_data = response.json()
                if res_data.get("errcode") == 0:
                    return True
                else:
                    logger.error(f"WeChat send failed (Attempt {i+1}): {res_data.get('errmsg')}")
            except Exception as e:
                logger.error(f"WeChat send exception (Attempt {i+1}): {e}")
        
        return False

    def send(self, title: str, content: str, level: str = "info") -> bool:
        """发送文本通知"""
        # Level indicator in Markdown
        level_map = {
            "info": "ℹ️ INFO",
            "warn": "⚠️ WARN",
            "error": "🚨 ERROR",
            "critical": "🔥 CRITICAL",
            "report": "📊 REPORT"
        }
        level_str = level_map.get(level.lower(), level.upper())
        
        data = {
            "msgtype": "markdown",
            "markdown": {
                "content": f"### {title}\n**Level**: {level_str}\n\n{content}"
            }
        }
        return self._post_with_retry(data)

    def send_card(self, card: dict[str, Any]) -> bool:
        """发送模板卡片消息"""
        data = {
            "msgtype": "template_card",
            "template_card": card
        }
        return self._post_with_retry(data)

    def test_connection(self) -> bool:
        """测试连接"""
        return self.send("Connection Test", "WeChat channel is active.")
