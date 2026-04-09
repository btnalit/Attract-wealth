# -*- coding: utf-8 -*-
"""
技术指标计算兵工厂 (Indicators)
源自: TradingAgents-CN 原版 `dataflows/technical/`
作用: 将原始的 OHLCV 字典/数据集，转换增扩为附带了各种计算因子的宽表。
使用 pandas-ta 作为引擎内核进行极限加速，如果没装则使用简单的原生 pandas。
"""
import pandas as pd
import logging
from src.dataflows.interface import IndicatorEngine

logger = logging.getLogger(__name__)

# 尝试挂载 pandas-ta 专业库
try:
    import pandas_ta as ta
    HAS_PTA = True
except ImportError:
    HAS_PTA = False
    logger.warning("未检测到 pandas-ta。将退化回基础 pandas 原生计算模式 (仅支持基础 MA)。推荐 pip install pandas-ta。")

class PandasTaIndicatorEngine(IndicatorEngine):
    def calculate_all(self, df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return df
            
        # 复制一份防止污染
        df_ta = df.copy()
        
        # 统一强制要求小写列名便于 pandas-ta 挂载
        col_map = {c: c.lower() for c in df_ta.columns}
        df_ta = df_ta.rename(columns=col_map)
        
        if HAS_PTA:
            # 使用 pandas_ta 的极速 C 底层库算出标准指标簇
            try:
                # 均线族
                df_ta.ta.sma(length=5, append=True)
                df_ta.ta.sma(length=10, append=True)
                df_ta.ta.sma(length=20, append=True)
                df_ta.ta.sma(length=60, append=True)
                
                # RSI 震荡指标
                df_ta.ta.rsi(length=14, append=True)
                
                # MACD
                df_ta.ta.macd(fast=12, slow=26, signal=9, append=True)
            except Exception as e:
                logger.error(f"pandas-ta 计算失败: {e}. 数据维度可能不够。")
        else:
            # 降级模式：纯原始计算
            if "close" in df_ta.columns:
                df_ta["sma_5"] = df_ta["close"].rolling(window=5).mean()
                df_ta["sma_10"] = df_ta["close"].rolling(window=10).mean()
                df_ta["sma_20"] = df_ta["close"].rolling(window=20).mean()
                df_ta["sma_60"] = df_ta["close"].rolling(window=60).mean()
                # 粗糙的 MACD
                ema12 = df_ta["close"].ewm(span=12, adjust=False).mean()
                ema26 = df_ta["close"].ewm(span=26, adjust=False).mean()
                df_ta["macd_12_26_9"] = ema12 - ema26
                
        # 截取掉最前面因为缺少周期算不出数字的 NaN 行
        df_ta.fillna(0.0, inplace=True)
        return df_ta
