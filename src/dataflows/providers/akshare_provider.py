# -*- coding: utf-8 -*-
"""
AkShare底层数据引擎 (防封特制版)
源自: TradingAgents-CN 原版 `dataflows/providers/`
作用: 通过内存 LRU Cache 作为防盾兵，以防止在自动寻猎中每隔30分钟被封IP。
"""
import time
import logging
import re
from typing import Dict, Any, List
import pandas as pd
import akshare as ak
from src.dataflows.interface import DataProvider

logger = logging.getLogger(__name__)

class AkShareProvider(DataProvider):
    def __init__(self):
        # 极简二级多级缓存： {"000001_hist": {"time": 12345678, "data": DataFrame}}
        self._cache: Dict[str, Dict[str, Any]] = {}
        # 历史 K 线防刷冷却参数 (半天算一次即可)
        self.HIST_TTL = 3600 * 4 
        # 实时报价防刷 (30秒)
        self.SPOT_TTL = 30
        
        # 启动时抓整板一次作为缓存底座
        self._spot_em_df: pd.DataFrame = None
        self._spot_em_timestamp: float = 0

        # T-41: 监控指标
        self._metrics = {
            "total_requests": 0,
            "success_requests": 0,
            "total_latency_ms": 0.0,
            "last_fields": [],
            "start_time": time.time()
        }

    def get_metrics(self) -> Dict[str, Any]:
        """返回监控指标 (T-41)"""
        total = self._metrics["total_requests"]
        success = self._metrics["success_requests"]
        avg_latency = self._metrics["total_latency_ms"] / total if total > 0 else 0.0
        return {
            "total_requests": total,
            "success_requests": success,
            "success_rate": success / total if total > 0 else 0.0,
            "avg_latency_ms": round(avg_latency, 2),
            "last_fields": self._metrics["last_fields"],
            "uptime_seconds": int(time.time() - self._metrics["start_time"])
        }

    def _get_spot_board(self) -> pd.DataFrame:
        """获取东方财富整板实时行情（比一个个拼字符串单点安全100倍）"""
        now = time.time()
        if self._spot_em_df is not None and (now - self._spot_em_timestamp < self.SPOT_TTL):
            return self._spot_em_df
        
        self._metrics["total_requests"] += 1
        start_t = time.time()
        try:
            logger.info("📦 [AkShare] 正在向东财拉取全市场实时盘口切片...")
            df = ak.stock_zh_a_spot_em()
            self._spot_em_df = df
            self._spot_em_timestamp = now
            
            # 更新指标
            self._metrics["success_requests"] += 1
            if not df.empty:
                self._metrics["last_fields"] = df.columns.tolist()
            
            return df
        except Exception as e:
            logger.error(f"❌ [AkShare] Spot EM 获取失败: {e}")
            return pd.DataFrame()
        finally:
            self._metrics["total_latency_ms"] += (time.time() - start_t) * 1000

    def get_realtime_quote(self, ticker: str) -> Dict[str, Any]:
        """获取单独个股最新数据"""
        df = self._get_spot_board()
        numeric_ticker = re.sub(r'[^\d]', '', ticker)
        
        if not df.empty:
            match = df[df["代码"] == numeric_ticker]
            if not match.empty:
                row = match.iloc[0]
                return {
                    "price": float(row["最新价"]) if pd.notna(row["最新价"]) else 0.0,
                    "change_pct": float(row["涨跌幅"]) if pd.notna(row["涨跌幅"]) else 0.0,
                    "volume_chg": float(row["换手率"]) if pd.notna(row["换手率"]) else 0.0,
                    "amount": float(row["成交额"]) if pd.notna(row["成交额"]) else 0.0,
                    "name": str(row["名称"])
                }
                
        # 降级方案：由于整板抓取可能被封锁导致为空，尝试单点拉取日线
        try:
            market_prefix = "sh" if numeric_ticker.startswith("6") else "sz"
            symbol = f"{market_prefix}{numeric_ticker}"
            df_hist = ak.stock_zh_a_daily(symbol=symbol, adjust="qfq")
            if not df_hist.empty:
                last_row = df_hist.iloc[-1]
                prev_row = df_hist.iloc[-2] if len(df_hist) > 1 else last_row
                close = float(last_row["close"])
                prev_close = float(prev_row["close"])
                return {
                    "price": close,
                    "change_pct": round((close - prev_close) / prev_close * 100, 2) if prev_close else 0.0,
                    "volume_chg": float(last_row.get("turnover", 0.0)),
                    "amount": float(last_row.get("amount", 0.0)),
                    "name": ticker.upper()
                }
        except Exception as e:
            logger.warning(f"Spot EM fallback failed for {ticker}: {e}")
            
        return {}

    def get_batch_realtime_quotes(self, tickers: List[str]) -> Dict[str, Dict[str, Any]]:
        result = {}
        df = self._get_spot_board()
        for t in tickers:
            numeric_ticker = re.sub(r'[^\d]', '', t)
            match = df[df["代码"] == numeric_ticker]
            if not match.empty:
                row = match.iloc[0]
                result[t] = {
                    "price": float(row["最新价"]) if pd.notna(row["最新价"]) else 0.0,
                    "change_pct": float(row["涨跌幅"]) if pd.notna(row["涨跌幅"]) else 0.0,
                }
        return result

    def get_historical_kline(self, ticker: str, limit: int = 100) -> pd.DataFrame:
        """获取日 K 线用于技术面计算"""
        cache_key = f"{ticker}_hist"
        now = time.time()
        
        if cache_key in self._cache:
            hit = self._cache[cache_key]
            if now - hit["time"] < self.HIST_TTL:
                return hit["data"]
                
        self._metrics["total_requests"] += 1
        start_t = time.time()
        try:
            logger.info(f"📊 [AkShare] 正在拉取 {ticker} 的历史日 K 线...")
            
            # 提取纯数字代码，并根据市场补齐前缀 sh600000, sz000001
            numeric_ticker = re.sub(r'[^\d]', '', ticker)
            market_prefix = "sh" if numeric_ticker.startswith("6") else "sz"
            symbol = f"{market_prefix}{numeric_ticker}"
            
            df = ak.stock_zh_a_daily(symbol=symbol, adjust="qfq")
            # 截取尾部符合限制的数据
            if len(df) > limit:
                df = df.tail(limit)
                
            # 格式化符合内部所需字段: date, open, high, low, close, volume
            if not df.empty:
                df.rename(columns={"date": "date", "open": "open", "high": "high", "low": "low", "close": "close", "volume": "volume"}, inplace=True)
                self._metrics["last_fields"] = df.columns.tolist()
                
            self._metrics["success_requests"] += 1
            self._cache[cache_key] = {"time": now, "data": df}
            return df
        except Exception as e:
            logger.error(f"❌ [AkShare] 拉取 {ticker} 报废: {e}")
            return pd.DataFrame()
        finally:
            self._metrics["total_latency_ms"] += (time.time() - start_t) * 1000
