import abc
from typing import Any

class BaseChannel(abc.ABC):
    """通知通道基类"""
    
    @abc.abstractmethod
    def send(self, title: str, content: str, level: str = "info") -> bool:
        """发送通知"""
        pass
    
    @abc.abstractmethod
    def send_card(self, card: dict[str, Any]) -> bool:
        """发送卡片消息"""
        pass
    
    @abc.abstractmethod
    def test_connection(self) -> bool:
        """测试连接"""
        pass
