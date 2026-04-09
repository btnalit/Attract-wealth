# -*- coding: utf-8 -*-
"""
A 股特定优化数据组装器 (Optimized China Data)
源自: TradingAgents-CN 原版 `dataflows/optimized_china_data.py`
作用: 将 Provider 抓取的原始 K 线，丢入技术面工厂切片后，重新组装为供 TradingVM 无脑使用的数据槽(Dict)。
"""
import logging
from typing import Dict, Any

from src.dataflows.providers.akshare_provider import AkShareProvider
from src.dataflows.technical.indicators import PandasTaIndicatorEngine

logger = logging.getLogger(__name__)

class ChinaDataAssembler:
    """A股数据组装流水线核心调度官"""
    
    def __init__(self):
        # 注入 A股爬虫提供商
        self.provider = AkShareProvider()
        # 注入技术指标算法库
        self.tech_engine = PandasTaIndicatorEngine()

    def fetch_agent_context(self, ticker: str) -> Dict[str, Any]:
        """
        提供给主 LangGraph 的一键黑盒获取函数
        将返回组装好的 { 实时价格, 当日 MA, 当日 MACD, ... }
        """
        context = {
            "ticker": ticker,
            "realtime": {},
            "technical_indicators": {},
            "market_environment": "A-Share T+1 System" # 后续可以接入大盘情绪
        }
        
        # 1. 抓此时此刻的盘口现价
        rt_quote = self.provider.get_realtime_quote(ticker)
        if rt_quote:
            context["realtime"] = rt_quote
            
        # 2. 抓用于计算长线历史的 K 线组 (前 100 天)
        hist_df = self.provider.get_historical_kline(ticker, limit=100)
        if hist_df is not None and not hist_df.empty:
            
            # 使用算法工厂算子附加一长串新列 (MA, MACD等)
            enriched_df = self.tech_engine.calculate_all(hist_df)
            
            if not enriched_df.empty:
                # 提取最新一天的指标字典
                latest_row = enriched_df.iloc[-1].to_dict()
                
                # 提取核心要紧的数据供大模型迅速扫描决策
                context["technical_indicators"] = {
                    "MA5": float(latest_row.get("sma_5", 0.0)),
                    "MA20": float(latest_row.get("sma_20", 0.0)),
                    "RSI_14": float(latest_row.get("rsi_14", 0.0)),
                    # 按照 pandas-ta macd 默认生成的列名形式
                    "MACD_DIF": float(latest_row.get("macd_12_26_9", 0.0)),
                    "MACD_HIST": float(latest_row.get("macdh_12_26_9", 0.0))
                }
                
                # 可以在此处附加简单的趋势判断供模型节省算力
                ma5 = context["technical_indicators"]["MA5"]
                ma20 = context["technical_indicators"]["MA20"]
                context["trend_signal"] = "BULL" if ma5 > ma20 else "BEAR"

        return context
