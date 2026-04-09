# -*- coding: utf-8 -*-
"""
数据流标准接口定义层 (Data Interface)
源自: TradingAgents-CN 原版 `dataflows/interface.py`
作用: 通过 Protocol 和抽象类制定取数规约，使上层智能体和技术工厂不用关心数据到底是来自 akshare 还是 tushare。
"""
from typing import Dict, Any, List, Optional
try:
    from typing import Protocol
except ImportError:
    from typing_extensions import Protocol
import pandas as pd

class DataProvider(Protocol):
    """底层提供商应该实现的取数接口"""
    
    def get_realtime_quote(self, ticker: str) -> Dict[str, Any]:
        """获取极少量的单票最新行情 (Price, Volume, Change)"""
        ...
        
    def get_historical_kline(self, ticker: str, limit: int = 100) -> pd.DataFrame:
        """获取用于算均线的日K线历史大全 (Open, High, Low, Close, Volume)"""
        ...
        
    def get_batch_realtime_quotes(self, tickers: List[str]) -> Dict[str, Dict[str, Any]]:
        """批量获取多只票的实时盘口 (解决循环请求防查水表)"""
        ...

class IndicatorEngine(Protocol):
    """算法引擎的标准入料加工接口"""
    
    def calculate_all(self, df: pd.DataFrame) -> pd.DataFrame:
        """接收清洗好的 OHLCV，吐出带有 MACD拉链、RSI 的 DataFrame"""
        ...
