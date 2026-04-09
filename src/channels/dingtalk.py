import os
import time
import hmac
import hashlib
import base64
import requests
import logging
import urllib.parse
from typing import Optional, Any
from .base import BaseChannel

logger = logging.getLogger(__name__)

class DingTalkChannel(BaseChannel):
    """钉钉通知通道 (Webhook + Signature)"""
    
    def __init__(self, webhook_url: Optional[str] = None, secret: Optional[str] = None):
        self.webhook_url = webhook_url or os.getenv("DINGTALK_WEBHOOK_URL")
        self.secret = secret or os.getenv("DINGTALK_SECRET")
        if not self.webhook_url:
            logger.warning("DINGTALK_WEBHOOK_URL is not set.")

    def _get_url(self) -> Optional[str]:
        if not self.webhook_url:
            return None
        if not self.secret:
            return self.webhook_url
        
        timestamp = str(round(time.time() * 1000))
        secret_enc = self.secret.encode('utf-8')
        string_to_sign = '{}\n{}'.format(timestamp, self.secret)
        string_to_sign_enc = string_to_sign.encode('utf-8')
        hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
        
        return f"{self.webhook_url}&timestamp={timestamp}&sign={sign}"

    def _post_with_retry(self, data: dict[str, Any], retries: int = 3) -> bool:
        url = self._get_url()
        if not url:
            logger.error("DingTalk URL not configured.")
            return False
            
        for i in range(retries):
            try:
                response = requests.post(url, json=data, timeout=10)
                response.raise_for_status()
                res_data = response.json()
                if res_data.get("errcode") == 0:
                    return True
                else:
                    logger.error(f"DingTalk send failed (Attempt {i+1}): {res_data.get('errmsg')}")
            except Exception as e:
                logger.error(f"DingTalk send exception (Attempt {i+1}): {e}")
        
        return False

    def send(self, title: str, content: str, level: str = "info") -> bool:
        """发送文本通知"""
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
                "title": title,
                "text": f"### {title}\n**Level**: {level_str}\n\n{content}"
            }
        }
        return self._post_with_retry(data)

    def send_card(self, card: dict[str, Any]) -> bool:
        """发送ActionCard消息"""
        data = {
            "msgtype": "actionCard",
            "actionCard": card
        }
        return self._post_with_retry(data)

    def test_connection(self) -> bool:
        """测试连接"""
        return self.send("Connection Test", "DingTalk channel is active.")
