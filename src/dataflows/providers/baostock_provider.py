# -*- coding: utf-8 -*-
"""
Baostock底层数据引擎
源自: 来财项目 T-05 任务
作用: 使用 Baostock API 获取股票数据，无需 token。
"""
import time
import logging
from typing import Dict, Any, List, Optional
import pandas as pd
import baostock as bs
from src.dataflows.interface import DataProvider

logger = logging.getLogger(__name__)

class BaostockProvider(DataProvider):
    def __init__(self):
        # 登录 Baostock
        lg = bs.login()
        if lg.error_code != '0':
            logger.error(f"❌ [Baostock] 登录失败: {lg.error_msg}")
            raise ConnectionError(f"Baostock login failed: {lg.error_msg}")
        
        # 缓存机制 (与 AkShareProvider 一致)
        self._cache: Dict[str, Dict[str, Any]] = {}
        self.HIST_TTL = 3600 * 4 
        self.SPOT_TTL = 30

    def __del__(self):
        """实例销毁时注销 Baostock 登录"""
        try:
            bs.logout()
        except:
            pass

    def _get_bs_code(self, ticker: str) -> str:
        """将 6 位代码转换为 Baostock 所需的 code (e.g. sh.600000)"""
        if "." in ticker:
            # 兼容 sh.600000 或 600000.sh 格式
            parts = ticker.split(".")
            if len(parts[0]) == 2: # sh.600000
                return ticker.lower()
            else: # 600000.sh
                return f"{parts[1]}.{parts[0]}".lower()
        
        if ticker.startswith("6"):
            return f"sh.{ticker}"
        elif ticker.startswith("8") or ticker.startswith("4"):
            return f"bj.{ticker}"
        else:
            return f"sz.{ticker}"

    def _get_latest_kline(self, bs_code: str) -> pd.DataFrame:
        """获取最新的日线数据作为实时近似"""
        now = time.time()
        cache_key = f"{bs_code}_latest"
        
        if cache_key in self._cache:
            hit = self._cache[cache_key]
            if now - hit["time"] < self.SPOT_TTL:
                return hit["data"]

        try:
            # 获取最近 5 个交易日的 K 线，取最后一个
            rs = bs.query_history_k_data_plus(
                code=bs_code,
                fields="date,code,open,high,low,close,pctChg,volume,amount",
                frequency="d", 
                adjustflag="3"
            )
            df = rs.get_data()
            if not df.empty:
                latest = df.tail(1)
                self._cache[cache_key] = {"time": now, "data": latest}
                return latest
        except Exception as e:
            logger.error(f"❌ [Baostock] 获取 {bs_code} 最新行情失败: {e}")
        
        return pd.DataFrame()

    def get_realtime_quote(self, ticker: str) -> Dict[str, Any]:
        """获取单独个股最新数据 (使用最近日线近似)"""
        bs_code = self._get_bs_code(ticker)
        df = self._get_latest_kline(bs_code)
        
        if df.empty:
            return {}
            
        row = df.iloc[0]
        # Baostock 返回的字段都是字符串
        return {
            "price": float(row["close"]),
            "change_pct": float(row["pctChg"]),
            "volume_chg": 0.0, # 无法从日 K 直接获取实时换手率
            "amount": float(row["amount"]),
            "name": ticker  # Baostock query_history_k_data_plus 不返回名称
        }

    def get_batch_realtime_quotes(self, tickers: List[str]) -> Dict[str, Dict[str, Any]]:
        """批量获取多只票的实时盘口 (Baostock 暂无真正的批量接口，通过循环+缓存实现)"""
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
        bs_code = self._get_bs_code(ticker)
        cache_key = f"{ticker}_hist"
        now = time.time()
        
        if cache_key in self._cache:
            hit = self._cache[cache_key]
            if now - hit["time"] < self.HIST_TTL:
                return hit["data"]
                
        try:
            logger.info(f"📊 [Baostock] 正在拉取 {ticker} 的历史日 K 线...")
            # 获取足够的数据
            rs = bs.query_history_k_data_plus(
                code=bs_code,
                fields="date,open,high,low,close,volume",
                frequency="d", 
                adjustflag="3" # 3: 不复权, 2: 前复权
            )
            df = rs.get_data()
            if df.empty:
                return pd.DataFrame()
                
            # Baostock 返回的是正序，截取最后 limit 条
            if len(df) > limit:
                df = df.tail(limit)
                
            # 转换为数值型 (Baostock 返回的都是字符串)
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = pd.to_numeric(df[col], errors='coerce')
                
            df = df.reset_index(drop=True)
            self._cache[cache_key] = {"time": now, "data": df}
            return df
        except Exception as e:
            logger.error(f"❌ [Baostock] 拉取 {ticker} 历史数据失败: {e}")
            return pd.DataFrame()
