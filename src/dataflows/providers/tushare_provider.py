# -*- coding: utf-8 -*-
"""
Tushare底层数据引擎
源自: 来财项目 T-05 任务
作用: 使用 Tushare Pro API 获取股票数据，并提供与 DataProvider 协议一致的接口。
"""
import os
import time
import logging
from typing import Dict, Any, List, Optional
import pandas as pd
import tushare as ts
from src.dataflows.interface import DataProvider

logger = logging.getLogger(__name__)

class TushareProvider(DataProvider):
    def __init__(self, token: Optional[str] = None):
        self.token = token or os.environ.get("TUSHARE_TOKEN")
        if not self.token:
            logger.error("❌ [Tushare] 未找到 TUSHARE_TOKEN 环境变量")
            raise ValueError("TUSHARE_TOKEN is required for TushareProvider")
        
        self.pro = ts.pro_api(self.token)
        
        # 缓存机制 (与 AkShareProvider 一致)
        self._cache: Dict[str, Dict[str, Any]] = {}
        self.HIST_TTL = 3600 * 4 
        self.SPOT_TTL = 30
        
        # 用于批量实时行情的缓存
        self._spot_cache_df: pd.DataFrame = None
        self._spot_timestamp: float = 0

    def _get_ts_code(self, ticker: str) -> str:
        """将 6 位代码转换为 Tushare 所需的 ts_code (e.g. 000001.SZ)"""
        if "." in ticker:
            return ticker
        if ticker.startswith("6"):
            return f"{ticker}.SH"
        elif ticker.startswith("8") or ticker.startswith("4"):
            return f"{ticker}.BJ"
        else:
            return f"{ticker}.SZ"

    def _get_latest_daily(self, ts_code: str) -> pd.DataFrame:
        """获取最新的日线数据作为实时近似"""
        now = time.time()
        cache_key = f"{ts_code}_latest"
        
        if cache_key in self._cache:
            hit = self._cache[cache_key]
            if now - hit["time"] < self.SPOT_TTL:
                return hit["data"]

        try:
            # 尝试拉取最近几天的，取最后一条
            df = self.pro.daily(ts_code=ts_code)
            if not df.empty:
                # Tushare 返回的是倒序的，第一行是最新的
                latest = df.head(1)
                self._cache[cache_key] = {"time": now, "data": latest}
                return latest
        except Exception as e:
            logger.error(f"❌ [Tushare] 获取 {ts_code} 最新行情失败: {e}")
        
        return pd.DataFrame()

    def get_realtime_quote(self, ticker: str) -> Dict[str, Any]:
        """获取单独个股最新数据 (使用 daily 接口最新一条近似)"""
        ts_code = self._get_ts_code(ticker)
        df = self._get_latest_daily(ts_code)
        
        if df.empty:
            return {}
            
        row = df.iloc[0]
        # Tushare daily 字段: ts_code, trade_date, open, high, low, close, pre_close, change, pct_chg, vol, amount
        return {
            "price": float(row["close"]),
            "change_pct": float(row["pct_chg"]),
            "volume_chg": 0.0,  # daily 接口无法直接获得实时换手率，设为 0 或计算
            "amount": float(row["amount"]) * 1000, # Tushare amount 单位是千元
            "name": ticker  # Tushare daily 不返回名称，需要额外查询 stock_basic
        }

    def get_batch_realtime_quotes(self, tickers: List[str]) -> Dict[str, Dict[str, Any]]:
        """批量获取多只票的实时盘口 (使用 daily 接口)"""
        now = time.time()
        # 如果请求频率太高，直接返回缓存或报错。Tushare 批量 daily 需要 trade_date。
        # 这里为了简化并符合协议，循环调用单票（带缓存）或者尝试拉取全市场。
        # Tushare 拉取全市场某日的 daily: pro.daily(trade_date='20231027')
        
        results = {}
        for ticker in tickers:
            quote = self.get_realtime_quote(ticker)
            if quote:
                results[ticker] = {
                    "price": quote["price"],
                    "change_pct": quote["change_pct"]
                }
        return results

    def get_historical_kline(self, ticker: str, limit: int = 100) -> pd.DataFrame:
        """获取日 K 线用于技术面计算"""
        ts_code = self._get_ts_code(ticker)
        cache_key = f"{ticker}_hist"
        now = time.time()
        
        if cache_key in self._cache:
            hit = self._cache[cache_key]
            if now - hit["time"] < self.HIST_TTL:
                return hit["data"]
                
        try:
            logger.info(f"📊 [Tushare] 正在拉取 {ticker} 的历史日 K 线...")
            # 获取足够的数据。由于 Tushare pro.daily 返回倒序，且默认条数较多，取前 limit 条再反转。
            df = self.pro.daily(ts_code=ts_code)
            if df.empty:
                return pd.DataFrame()
                
            df = df.head(limit)
            # 统一列名并转为正序
            # 转换 trade_date (YYYYMMDD) 为 YYYY-MM-DD
            df['date'] = pd.to_datetime(df['trade_date']).dt.strftime('%Y-%m-%d')
            df = df.rename(columns={
                "open": "open", 
                "high": "high", 
                "low": "low", 
                "close": "close", 
                "vol": "volume"
            })
            # Tushare vol 是手，转换回股数 (根据习惯，AkShare 通常是股或手，这里保持与后续逻辑兼容，通常 AkShare 是股)
            # 但 AkShareProvider 只是 rename，没改量级。
            
            df = df[["date", "open", "high", "low", "close", "volume"]]
            df = df.sort_values("date").reset_index(drop=True)
            
            self._cache[cache_key] = {"time": now, "data": df}
            return df
        except Exception as e:
            logger.error(f"❌ [Tushare] 拉取 {ticker} 历史数据失败: {e}")
            return pd.DataFrame()
