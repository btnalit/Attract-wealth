import asyncio
import logging
from typing import Optional, Any
from .base import BaseChannel

logger = logging.getLogger(__name__)

class ChannelManager:
    """多通道管理器"""
    
    def __init__(self):
        self.channels: dict[str, BaseChannel] = {}
    
    def register(self, name: str, channel: BaseChannel):
        """注册通知通道"""
        self.channels[name] = channel
        logger.info(f"Notification channel registered: {name}")
    
    async def notify_all(self, title: str, content: str, level: str = "info") -> None:
        """向所有已注册通道并行异步发送通知"""
        if not self.channels:
            logger.warning("No channels registered for notification.")
            return
            
        tasks = [
            asyncio.to_thread(channel.send, title, content, level)
            for channel in self.channels.values()
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for name, res in zip(self.channels.keys(), results):
            if isinstance(res, Exception):
                logger.error(f"Notify error in channel {name}: {res}")
            elif not res:
                logger.error(f"Notify failed for channel {name}")
    
    async def notify_selected(self, channel_names: list[str], title: str, content: str, level: str = "info") -> None:
        """向指定通道并行异步发送通知"""
        tasks = []
        target_names = []
        for name in channel_names:
            if name in self.channels:
                tasks.append(asyncio.to_thread(self.channels[name].send, title, content, level))
                target_names.append(name)
            else:
                logger.warning(f"Notification channel not found: {name}")
        
        if not tasks:
            return
            
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for name, res in zip(target_names, results):
            if isinstance(res, Exception):
                logger.error(f"Notify error in channel {name}: {res}")
            elif not res:
                logger.error(f"Notify failed for channel {name}")
    
    def send_daily_report(self, report: dict[str, Any]) -> None:
        """发送每日交易报告 (同步，格式化输出)"""
        title = f"每日反思报告 - {report.get('date', 'Today')}"
        
        # Format the content
        content_lines = []
        for k, v in report.items():
            if k == "date": continue
            # Convert keys to readable labels if possible
            label = k.replace("_", " ").title()
            content_lines.append(f"- **{label}**: {v}")
        
        content = "\n".join(content_lines)
        
        # Synchronous broadcast
        for name, channel in self.channels.items():
            success = channel.send(title, content, level="report")
            if not success:
                logger.error(f"Sync daily report failed for channel {name}")
