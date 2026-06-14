# -*- coding: utf-8 -*-
"""
A 股特定优化数据组装器 (Optimized China Data)
源自: TradingAgents-CN 原版 `dataflows/optimized_china_data.py`
作用: 将多源 Provider 抓取的原始 K 线 + 衍生数据，丢入技术面工厂切片后，
重新组装为供 TradingVM / Analyst 无脑使用的数据槽(Dict)。

重构要点（A 股分析增强）:
- 改走 DataSourceManager.data_manager（享受多源 fallback：akshare→baostock→sina_tencent）
- context 从 6 个字段扩展到全维度：技术指标全量 + 龙虎榜/资金流/板块/财务/融券/风险标记
- 向后兼容：technical_indicators 字段保留原有 5 项，仅做增量扩展
"""
import logging
import re
from typing import Any, Dict

import pandas as pd

from src.dataflows.source_manager import data_manager
from src.dataflows.technical.indicators import PandasTaIndicatorEngine

logger = logging.getLogger(__name__)


def _numeric_code(ticker: str) -> str:
    return re.sub(r"[^\d]", "", ticker)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        result = float(value)
        return result if result == result else default
    except (TypeError, ValueError):
        return default


class ChinaDataAssembler:
    """A 股数据组装流水线核心调度官"""

    def __init__(self):
        # 走多源管理器（自动 fallback），不再直接持有单一 AkShareProvider
        self.data_manager = data_manager
        # 注入技术指标算法库
        self.tech_engine = PandasTaIndicatorEngine()

    # -------------------------
    # 数据获取（统一走 data_manager 多源 fallback）
    # -------------------------
    def _get_realtime(self, numeric: str) -> Dict[str, Any]:
        provider = self.data_manager.get_provider_instance()
        if provider is None:
            return {}
        try:
            fn = getattr(provider, "get_realtime_quote", None)
            if callable(fn):
                return fn(numeric) or {}
        except Exception as exc:  # noqa: BLE001
            logger.warning("realtime quote failed for %s: %s", numeric, exc)
        return {}

    def _get_kline(self, numeric: str, limit: int = 100) -> pd.DataFrame:
        provider = self.data_manager.get_provider_instance()
        if provider is None:
            return pd.DataFrame()
        try:
            fn = getattr(provider, "get_historical_kline", None)
            if callable(fn):
                df = fn(numeric, limit=limit)
                if isinstance(df, pd.DataFrame) and not df.empty:
                    return df
        except Exception as exc:  # noqa: BLE001
            logger.warning("kline fetch failed for %s: %s", numeric, exc)
        return pd.DataFrame()

    # -------------------------
    # 主入口：组装完整 agent context
    # -------------------------
    def fetch_agent_context(self, ticker: str) -> Dict[str, Any]:
        """
        提供给主 LangGraph 的一键黑盒获取函数。
        返回组装好的 { 实时价格, 技术指标(全量), 龙虎榜, 资金流, 板块, 财务, 风险标记 }。
        所有衍生维度软失败：拿不到返回空，不阻断分析链路。
        """
        numeric = _numeric_code(ticker)
        context: Dict[str, Any] = {
            "ticker": ticker,
            "realtime": {},
            "technical_indicators": {},
            "dragon_tiger": [],
            "money_flow": {},
            "sector_info": {},
            "financials": {},
            "margin": {},
            "ashare_flags": {},
            "announcements": [],
            "market_environment": "A-Share T+1 System",
        }

        # 1. 实时报价
        rt_quote = self._get_realtime(numeric)
        if rt_quote:
            context["realtime"] = rt_quote

        # 2. 历史 K 线 + 技术指标计算（全量，不只 5 项）
        hist_df = self._get_kline(numeric, limit=100)
        if hist_df is not None and not hist_df.empty:
            enriched_df = self.tech_engine.calculate_all(hist_df)
            if not enriched_df.empty:
                latest_row = enriched_df.iloc[-1]
                context["technical_indicators"] = self._extract_technical_indicators(latest_row)
                # 保留轻量趋势判断（向后兼容）
                ma5 = context["technical_indicators"].get("MA5", 0.0)
                ma20 = context["technical_indicators"].get("MA20", 0.0)
                context["trend_signal"] = "BULL" if ma5 > ma20 else "BEAR"
                # 附带最近 30 日 K 线序列供前端图表 + 规则引擎使用
                context["kline_recent"] = self._serialize_recent_kline(enriched_df.tail(30))

        # 3. A 股衍生数据（全部走 data_manager 多源兜底，软失败）
        context["dragon_tiger"] = self.data_manager.get_dragon_tiger(ticker)
        context["money_flow"] = self.data_manager.get_money_flow(ticker)
        context["sector_info"] = self.data_manager.get_sector_info(ticker)
        context["financials"] = self.data_manager.get_financial_abstract(ticker)
        context["margin"] = self.data_manager.get_margin(ticker)
        context["ashare_flags"] = self.data_manager.get_stock_flags(ticker)
        context["announcements"] = self.data_manager.get_announcements(ticker, limit=10)

        # 4. 汇总数据源快照（供前端展示数据来源与降级状态）
        try:
            context["data_source"] = {
                "current_provider": self.data_manager.get_current_provider_name(),
                "providers": self.data_manager.list_providers(),
            }
        except Exception:  # noqa: BLE001
            context["data_source"] = {}

        # 5. 数据新鲜度 + 完整度评估（供规则引擎降低置信度 + 前端展示）
        context["data_freshness"] = self._assess_data_freshness(context)

        return context

    def _assess_data_freshness(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """评估各维度数据的新鲜度和完整度。

        返回:
        {
            "dimensions": {dim: {"available": bool, "stale": bool, "note": str}},
            "completeness": float,  # 0-1，有数据的维度占比
            "is_stale": bool,  # 关键维度是否过时
            "stale_penalty": float,  # 建议的置信度惩罚（0-30）
        }
        """
        import time as _time
        from datetime import datetime, timedelta

        # 检查 K 线最新日期是否过时（超过 3 个交易日 ≈ 5 天）
        kline_recent = context.get("kline_recent") or []
        kline_date_str = str(kline_recent[-1].get("date", "")) if kline_recent else ""
        kline_stale = False
        if kline_date_str:
            try:
                kline_date = datetime.strptime(kline_date_str[:10], "%Y-%m-%d")
                days_old = (datetime.now() - kline_date).days
                kline_stale = days_old > 5  # 超过 5 天视为过时（含周末）
            except (ValueError, TypeError):
                pass

        # 各维度可用性
        dims = {
            "realtime": {"available": bool(context.get("realtime")), "stale": False},
            "technical_indicators": {"available": bool(context.get("technical_indicators")), "stale": kline_stale},
            "kline_recent": {"available": len(kline_recent) > 0, "stale": kline_stale},
            "money_flow": {"available": bool(context.get("money_flow")), "stale": False},
            "dragon_tiger": {"available": bool(context.get("dragon_tiger")), "stale": False},
            "sector_info": {"available": bool(context.get("sector_info")), "stale": False},
            "financials": {"available": bool(context.get("financials")), "stale": False},
            "ashare_flags": {"available": bool(context.get("ashare_flags")), "stale": False},
        }

        # 完整度：有数据的维度占比
        total_dims = len(dims)
        available_count = sum(1 for d in dims.values() if d["available"])
        completeness = round(available_count / total_dims, 2) if total_dims else 0.0

        # 关键维度过时 → 置信度惩罚
        is_stale = kline_stale
        stale_penalty = 0.0
        if kline_stale:
            stale_penalty = 20.0
        if completeness < 0.4:
            stale_penalty = max(stale_penalty, 25.0)  # 数据严重不全额外惩罚

        return {
            "dimensions": dims,
            "completeness": completeness,
            "is_stale": is_stale,
            "stale_penalty": stale_penalty,
            "kline_latest_date": kline_date_str,
            "assessed_at": int(_time.time()),
        }

    # -------------------------
    # 指标提取辅助
    # -------------------------
    def _extract_technical_indicators(self, latest_row: pd.Series) -> Dict[str, Any]:
        """从计算后的 K 线最新行提取全量技术指标。

        向后兼容：保留原有 MA5/MA20/RSI_14/MACD_DIF/MACD_HIST 五项，
        新增 MA10/MA60 等所有 pandas-ta 已计算的字段。

        注意：pandas-ta 不同版本列名大小写不一致（有 pandas_ta 时是大写
        SMA_5/RSI_14，降级纯 pandas 模式是小写 sma_5），这里同时兼容两种。
        """
        def _g(*keys: str, default: float = 0.0) -> float:
            """按优先级尝试多个候选列名，首个非 None 即返回。"""
            for key in keys:
                val = latest_row.get(key)
                if val is not None:
                    return _safe_float(val)
            return default

        # 原有 5 项（向后兼容，字段名不变）——同时支持大小写
        indicators: Dict[str, Any] = {
            "MA5": _g("sma_5", "SMA_5"),
            "MA20": _g("sma_20", "SMA_20"),
            "RSI_14": _g("rsi_14", "RSI_14"),
            "MACD_DIF": _g("macd_12_26_9", "MACD_12_26_9"),
            "MACD_HIST": _g("macdh_12_26_9", "MACDh_12_26_9"),
        }
        # 新增项（增量，不覆盖原有字段）
        indicators.update({
            "MA10": _g("sma_10", "SMA_10"),
            "MA60": _g("sma_60", "SMA_60"),
            "MACD_SIGNAL": _g("macds_12_26_9", "MACDs_12_26_9"),
            "close": _g("close"),
            "volume": _g("volume"),
        })
        # 附带原始 OHLCV 供规则引擎和前端图表
        for field in ("open", "high", "low", "close", "volume"):
            val = latest_row.get(field)
            if val is not None:
                indicators[field.upper()] = _safe_float(val)
        return indicators

    def _serialize_recent_kline(self, df: pd.DataFrame) -> list[Dict[str, Any]]:
        """序列化最近 N 日 K 线为 list[dict]，供前端图表和规则引擎使用。"""
        if df is None or df.empty:
            return []
        # pandas-ta 列名大小写兼容
        def _pick(row, *keys):
            for k in keys:
                if k in row:
                    return _safe_float(row[k])
            return 0.0

        records = []
        for _, row in df.iterrows():
            records.append({
                "date": str(row.get("date", "")),
                "open": _safe_float(row.get("open")),
                "high": _safe_float(row.get("high")),
                "low": _safe_float(row.get("low")),
                "close": _safe_float(row.get("close")),
                "volume": _safe_float(row.get("volume")),
                "ma5": _pick(row, "sma_5", "SMA_5"),
                "ma20": _pick(row, "sma_20", "SMA_20"),
            })
        return records
