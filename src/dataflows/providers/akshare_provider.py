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
from src.dataflows.interface import DataProvider, DefaultAShareExtendedMixin

logger = logging.getLogger(__name__)


def resolve_ashare_symbol(numeric: str) -> str:
    """
    根据纯数字代码推导 akshare 历史接口所需的带前缀符号 (sh/sz/bj)。

    修复原 `startswith("6")` 的缺陷：原逻辑漏了科创板(688)/创业板(300)/
    北交所(8/4 开头)，导致这些股票取不到 K 线。
    规则参照沪深北交所代码段划分。
    """
    code = re.sub(r'[^\d]', '', numeric)
    if not code:
        return code
    # 上交所：60/68 主板+科创板，90 老B股，11/13 可转债，5x ETF/基金
    if code.startswith(("60", "68", "90", "11", "13", "50", "51", "52", "53", "54", "55", "56", "58")):
        return f"sh{code}"
    # 深交所：00 主板，30 创业板，12 可转债，15/16/18 LOF/ETF
    if code.startswith(("00", "30", "12", "15", "16", "18")):
        return f"sz{code}"
    # 北交所：8 开头（83/87/92 等），920 新代码段，43 原新三板精选层，4 开头
    if code.startswith(("8", "920", "43", "4")):
        return f"bj{code}"
    # 兜底默认深交所（A股绝大多数代码以 0/3 开头）
    return f"sz{code}"


class AkShareProvider(DataProvider, DefaultAShareExtendedMixin):
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
            symbol = resolve_ashare_symbol(numeric_ticker)
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
            symbol = resolve_ashare_symbol(numeric_ticker)
            
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

    # ============================================
    # A 股衍生数据接口（龙虎榜/资金流/板块/财务/融券/风险标记）
    # 全部软失败：拿不到数据返回空，绝不阻断 analyze 链路
    # ============================================

    def _track_extended_call(self, start_t: float, *, ok: bool):
        self._metrics["total_requests"] += 1
        if ok:
            self._metrics["success_requests"] += 1
        self._metrics["total_latency_ms"] += (time.time() - start_t) * 1000

    def _spot_row_for(self, numeric_ticker: str) -> Dict[str, Any]:
        """从东财整板快照里取单票行（复用 _get_spot_board 防封缓存）。"""
        df = self._get_spot_board()
        if df is None or df.empty:
            return {}
        match = df[df["代码"] == numeric_ticker]
        if match.empty:
            return {}
        return match.iloc[0].to_dict()

    def get_dragon_tiger(self, ticker: str) -> List[Dict[str, Any]]:
        """龙虎榜：近 N 日上榜明细（营业部/机构席位/买卖净额）。

        数据源：ak.stock_lhb_detail_em（东财龙虎榜详情）。
        返回 [{"date","reason","seat","buy","sale","net"}, ...]；无上榜返回 []。
        """
        start_t = time.time()
        numeric = re.sub(r'[^\d]', '', ticker)
        try:
            df = ak.stock_lhb_detail_em(start_date="", end_date="")
            if df is None or df.empty:
                self._track_extended_call(start_t, ok=True)
                return []
            hit = df[df["代码"].astype(str).str.contains(numeric)] if "代码" in df.columns else df.iloc[0:0]
            if hit.empty:
                self._track_extended_call(start_t, ok=True)
                return []
            records: List[Dict[str, Any]] = []
            for _, row in hit.head(20).iterrows():
                records.append({
                    "date": str(row.get("上榜日", "")),
                    "reason": str(row.get("解读", "")),
                    "name": str(row.get("名称", "")),
                    "close": _safe_float(row.get("收盘价")),
                    "change_pct": _safe_float(row.get("涨跌幅")),
                    "net": _safe_float(row.get("龙虎榜净买额")),
                    "buy_total": _safe_float(row.get("买入额")),
                    "sale_total": _safe_float(row.get("卖出额")),
                })
            self._track_extended_call(start_t, ok=True)
            return records
        except Exception as exc:  # noqa: BLE001
            logger.warning("[AkShare] 龙虎榜拉取失败 %s: %s", ticker, exc)
            self._track_extended_call(start_t, ok=False)
            return []

    def get_money_flow(self, ticker: str) -> Dict[str, Any]:
        """个股资金流向：主力净流入、超大/大/中/小单分解（近 N 日）。

        数据源：ak.stock_individual_fund_flow（东财个股资金流）。
        """
        start_t = time.time()
        numeric = re.sub(r'[^\d]', '', ticker)
        try:
            df = ak.stock_individual_fund_flow(stock=numeric, market=_market_short(numeric))
            if df is None or df.empty:
                self._track_extended_call(start_t, ok=True)
                return {}
            recent = df.tail(10)
            latest = df.iloc[-1].to_dict() if not df.empty else {}
            self._track_extended_call(start_t, ok=True)
            return {
                "latest_date": str(latest.get("日期", "")),
                "main_net": _safe_float(latest.get("主力净流入-净额")),
                "main_net_pct": _safe_float(latest.get("主力净流入-净占比")),
                "super_large_net": _safe_float(latest.get("超大单净流入-净额")),
                "large_net": _safe_float(latest.get("大单净流入-净额")),
                "medium_net": _safe_float(latest.get("中单净流入-净额")),
                "small_net": _safe_float(latest.get("小单净流入-净额")),
                "recent_main_net_sum": float(pd.to_numeric(recent.get("主力净流入-净额", 0), errors="coerce").fillna(0).sum()),
                "history": [
                    {
                        "date": str(r.get("日期", "")),
                        "main_net": _safe_float(r.get("主力净流入-净额")),
                    }
                    for _, r in recent.iterrows()
                ],
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("[AkShare] 资金流拉取失败 %s: %s", ticker, exc)
            self._track_extended_call(start_t, ok=False)
            return {}

    def get_sector_info(self, ticker: str) -> Dict[str, Any]:
        """所属行业/概念板块 + 板块当日涨跌幅 + 板块资金流。

        数据源：ak.stock_individual_info_em（所属行业/概念）+
                ak.stock_board_industry_name_em（板块行情，软失败）。
        """
        start_t = time.time()
        numeric = re.sub(r'[^\d]', '', ticker)
        try:
            df = ak.stock_individual_info_em(symbol=numeric)
            if df is None or df.empty:
                self._track_extended_call(start_t, ok=True)
                return {}
            info = dict(zip(df["item"], df["value"])) if "item" in df.columns else {}
            industry = str(info.get("行业", ""))

            result = {
                "name": str(info.get("股票简称", "")),
                "industry": industry,
                "concept": str(info.get("概念", "")),
                "list_date": str(info.get("上市时间", "")),
                "total_shares": _safe_float(info.get("总股本")),
                "circulating_shares": _safe_float(info.get("流通股")),
                "total_market_cap": _safe_float(info.get("总市值")),
                "circulating_market_cap": _safe_float(info.get("流通市值")),
            }

            # 扩展：查板块当日行情（软失败，限流时跳过）
            if industry:
                sector_perf = self._fetch_sector_performance(industry)
                if sector_perf:
                    result["sector_performance"] = sector_perf

            self._track_extended_call(start_t, ok=True)
            return result
        except Exception as exc:  # noqa: BLE001
            logger.warning("[AkShare] 板块信息拉取失败 %s: %s", ticker, exc)
            self._track_extended_call(start_t, ok=False)
            return {}

    def _fetch_sector_performance(self, industry: str) -> Dict[str, Any]:
        """查行业板块当日涨跌（软失败）。数据源：stock_board_industry_name_em。"""
        try:
            df = ak.stock_board_industry_name_em()
            if df is None or df.empty:
                return {}
            # 按板块名匹配
            name_col = "板块名称" if "板块名称" in df.columns else None
            if not name_col:
                return {}
            match = df[df[name_col].astype(str) == industry]
            if match.empty:
                return {}
            row = match.iloc[0]
            return {
                "sector_name": str(row.get("板块名称", industry)),
                "sector_change_pct": _safe_float(row.get("涨跌幅")),
                "sector_turnover": _safe_float(row.get("换手率")),
                "sector_amount": _safe_float(row.get("总市值")),
                "leader_stock": str(row.get("领涨股票", "")),
                "leader_change_pct": _safe_float(row.get("领涨股票-涨跌幅")),
            }
        except Exception:  # noqa: BLE001
            return {}

    def get_financial_abstract(self, ticker: str) -> Dict[str, Any]:
        """财务摘要：PE/PB/ROE/营收/净利润/毛利率等核心指标。

        数据源：ak.stock_financial_abstract（东财财务摘要）。
        """
        start_t = time.time()
        numeric = re.sub(r'[^\d]', '', ticker)
        try:
            df = ak.stock_financial_abstract(symbol=f"{'sh' if numeric.startswith('6') else 'sz'}{numeric}")
            if df is None or df.empty:
                self._track_extended_call(start_t, ok=True)
                return {}
            latest = df.iloc[:, :2] if df.shape[1] >= 2 else df
            kv = {}
            cols = list(df.columns)
            if len(cols) >= 2:
                for idx in range(len(df)):
                    kv[str(df.iloc[idx, 0])] = _safe_float(df.iloc[idx, 1])
            self._track_extended_call(start_t, ok=True)
            return {
                "indicators": kv,
                "report_date": str(cols[1]) if len(cols) >= 2 else "",
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("[AkShare] 财务摘要拉取失败 %s: %s", ticker, exc)
            self._track_extended_call(start_t, ok=False)
            return {}

    def get_margin(self, ticker: str) -> Dict[str, Any]:
        """融资融券：融资余额、融券余额、近 N 日变化。

        数据源：ak.stock_margin_detail_sse / stock_margin_detail_szse（沪深分别）。
        注意：接口签名随 akshare 版本变化，统一 try/except 软失败。
        """
        start_t = time.time()
        numeric = re.sub(r'[^\d]', '', ticker)
        try:
            if numeric.startswith("6"):
                df = ak.stock_margin_detail_sse(date="", start_date="", end_date="")
            else:
                df = ak.stock_margin_detail_szse(date="", start_date="", end_date="")
            if df is None or df.empty:
                self._track_extended_call(start_t, ok=True)
                return {}
            # 按代码过滤
            code_col = "信用交易标的证券代码" if "信用交易标的证券代码" in df.columns else ("代码" if "代码" in df.columns else None)
            if code_col:
                hit = df[df[code_col].astype(str).str.contains(numeric)]
            else:
                hit = df.iloc[0:0]
            if hit.empty:
                self._track_extended_call(start_t, ok=True)
                return {}
            latest = hit.iloc[-1].to_dict()
            self._track_extended_call(start_t, ok=True)
            return {
                "date": str(latest.get("信用交易日期", latest.get("日期", ""))),
                "finance_balance": _safe_float(latest.get("融资余额")),
                "finance_buy": _safe_float(latest.get("融资买入额")),
                "securities_balance": _safe_float(latest.get("融券余额")),
                "securities_volume": _safe_float(latest.get("融券余量")),
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("[AkShare] 融资融券拉取失败 %s: %s", ticker, exc)
            self._track_extended_call(start_t, ok=False)
            return {}

    def get_stock_flags(self, ticker: str) -> Dict[str, Any]:
        """A 股风险/状态标记：ST/退市风险/停牌/涨跌停状态。

        综合 _get_spot_board 整板快照判断（名称含 ST/涨跌幅触及 ±10%/±20%）。
        """
        start_t = time.time()
        numeric = re.sub(r'[^\d]', '', ticker)
        try:
            row = self._spot_row_for(numeric)
            if not row:
                self._track_extended_call(start_t, ok=True)
                return {}
            name = str(row.get("名称", ""))
            change_pct = _safe_float(row.get("涨跌幅"))
            price = _safe_float(row.get("最新价"))
            prev_close = price / (1 + change_pct / 100) if price and change_pct else 0.0

            flags: List[str] = []
            if "ST" in name.upper() or "*ST" in name:
                flags.append("ST")
            # 涨跌停判断：科创板/创业板 ±20%，其余 ±10%（ST 股 ±5%，此处从简）
            limit_pct = 20.0 if numeric.startswith(("30", "68")) else 10.0
            if change_pct >= limit_pct - 0.01:
                flags.append("LIMIT_UP")
            elif change_pct <= -limit_pct + 0.01:
                flags.append("LIMIT_DOWN")
            # 停牌：最新价为 0 或涨跌幅为 0 且无成交额
            amount = _safe_float(row.get("成交额"))
            if price == 0 or (change_pct == 0 and amount == 0):
                flags.append("SUSPENDED")

            self._track_extended_call(start_t, ok=True)
            return {
                "name": name,
                "flags": flags,
                "is_st": "ST" in flags,
                "limit_up": "LIMIT_UP" in flags,
                "limit_down": "LIMIT_DOWN" in flags,
                "suspended": "SUSPENDED" in flags,
                "price": price,
                "prev_close": round(prev_close, 4) if prev_close else 0.0,
                "change_pct": change_pct,
                "limit_pct": limit_pct,
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("[AkShare] 风险标记拉取失败 %s: %s", ticker, exc)
            self._track_extended_call(start_t, ok=False)
            return {}

    def get_announcements(self, ticker: str, limit: int = 10) -> List[Dict[str, Any]]:
        """个股公告：重大事项、业绩预告、增减持等。

        数据源：akshare 公告接口（软失败，接口名随版本可能变化）。
        返回 [{"date","title","type","content"}, ...]。
        """
        start_t = time.time()
        numeric = re.sub(r'[^\d]', '', ticker)
        try:
            # 尝试多个 akshare 公告接口（接口名随版本变化，软失败）
            df = None
            for api_name in ("stock_notice_report", "stock_zh_a_disclosure_relation"):
                fn = getattr(ak, api_name, None)
                if fn is None:
                    continue
                try:
                    df = fn(symbol=numeric) if api_name == "stock_notice_report" else fn(symbol=f"{'sh' if numeric.startswith('6') else 'sz'}{numeric}")
                    if df is not None and not df.empty:
                        break
                except Exception:  # noqa: BLE001
                    continue
            if df is None or df.empty:
                self._track_extended_call(start_t, ok=True)
                return []

            records: List[Dict[str, Any]] = []
            for _, row in df.head(limit).iterrows():
                records.append({
                    "date": str(row.get("公告日期", row.get("日期", ""))),
                    "title": str(row.get("公告标题", row.get("标题", ""))),
                    "type": str(row.get("公告类型", row.get("类型", ""))),
                    "content": str(row.get("公告内容", row.get("内容", "")))[:500],
                })
            self._track_extended_call(start_t, ok=True)
            return records
        except Exception as exc:  # noqa: BLE001
            logger.warning("[AkShare] 公告拉取失败 %s: %s", ticker, exc)
            self._track_extended_call(start_t, ok=False)
            return []


def _safe_float(value: Any) -> float:
    """容错转 float：None/异常字符串返回 0.0。"""
    try:
        if value is None:
            return 0.0
        result = float(value)
        return result if result == result else 0.0  # NaN 检测
    except (TypeError, ValueError):
        return 0.0


def _market_short(numeric: str) -> str:
    """stock_individual_fund_flow 需要 market 参数：sh/sz/bj。"""
    sym = resolve_ashare_symbol(numeric)
    return sym[:2] if sym else "sh"
