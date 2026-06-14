# -*- coding: utf-8 -*-
"""
新浪/腾讯 备用数据引擎 (SinaTencentProvider)

设计目标：完全不走东方财富，作为 akshare/efinance（均依赖东财）被限流时的
稳定降级源。仅依赖 urllib + pandas，无第三方金融库，接口公开稳定。

数据覆盖（聚焦行情/K线，衍生数据返回空由上层多源兜底）：
- 实时报价：新浪 hq.sinajs.cn（A股标准实时接口，数十年稳定）
- 历史日K：腾讯 web.ifzq.gtimg.cn（前复权日K）
- 批量报价：循环新浪接口（小批量场景）

注意：龙虎榜/资金流/财务等衍生数据本源不提供，由 DefaultAShareExtendedMixin
返回空，上层 _call_extended 会自动降级到 akshare/baostock。
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List
from urllib.parse import quote

import pandas as pd

from src.dataflows.interface import DataProvider, DefaultAShareExtendedMixin

logger = logging.getLogger(__name__)


def _http_get(url: str, *, timeout: float = 8.0, headers: dict | None = None) -> str:
    """轻量 HTTP GET，返回文本。失败抛异常由调用方软处理。"""
    import urllib.request

    req_headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AttractWealth/1.0"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        # 新浪接口是 gbk，腾讯是 utf-8；统一先按 bytes 读再尝试解码
        raw = resp.read()
    for encoding in ("gbk", "utf-8", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _sina_symbol(numeric: str) -> str:
    """新浪/腾讯接口需要的带市场前缀代码：sh600000 / sz000001 / sh688981。"""
    code = re.sub(r"[^\d]", "", numeric)
    if code.startswith("6"):  # 沪市主板/科创板
        return f"sh{code}"
    if code.startswith(("0", "3")):  # 深市主板/创业板
        return f"sz{code}"
    if code.startswith(("8", "4", "9")):  # 北交所
        return f"bj{code}"
    return f"sz{code}"


def _tencent_symbol(numeric: str) -> str:
    """腾讯日K接口代码：sh600000 / sz000001（与新浪同构）。"""
    return _sina_symbol(numeric)


class SinaTencentProvider(DataProvider, DefaultAShareExtendedMixin):
    """新浪/腾讯数据源（不走东财），作为限流降级备用。"""

    def __init__(self):
        # 二级缓存（与 AkShareProvider 风格一致）
        self._cache: Dict[str, Dict[str, Any]] = {}
        self.HIST_TTL = 3600 * 4
        self.SPOT_TTL = 30
        self._spot_cache: Dict[str, Dict[str, Any]] = {}
        self._spot_cache_ts: float = 0.0
        self._metrics = {
            "total_requests": 0,
            "success_requests": 0,
            "total_latency_ms": 0.0,
            "start_time": time.time(),
        }

    def _track(self, start_t: float, *, ok: bool) -> None:
        self._metrics["total_requests"] += 1
        if ok:
            self._metrics["success_requests"] += 1
        self._metrics["total_latency_ms"] += (time.time() - start_t) * 1000

    def get_metrics(self) -> Dict[str, Any]:
        total = self._metrics["total_requests"]
        success = self._metrics["success_requests"]
        return {
            "total_requests": total,
            "success_requests": success,
            "success_rate": success / total if total > 0 else 0.0,
            "avg_latency_ms": round(self._metrics["total_latency_ms"] / total, 2) if total > 0 else 0.0,
            "uptime_seconds": int(time.time() - self._metrics["start_time"]),
        }

    # -------------------------
    # 实时报价（新浪）
    # -------------------------
    def get_realtime_quote(self, ticker: str) -> Dict[str, Any]:
        """新浪实时行情：返回 price/change_pct/volume/amount/name。"""
        numeric = re.sub(r"[^\d]", "", ticker)
        cache_key = f"sina_spot_{numeric}"
        now = time.time()
        cached = self._spot_cache.get(cache_key)
        if cached and (now - self._spot_cache_ts < self.SPOT_TTL):
            return cached

        start_t = time.time()
        symbol = _sina_symbol(numeric)
        url = f"http://hq.sinajs.cn/list={symbol}"
        try:
            text = _http_get(url, headers={"Referer": "https://finance.sina.com.cn/"})
            # 格式：var hq_str_sh600000="名称,昨收,今收,现价,最高,最低,买1,卖1,成交量,成交额,..."
            match = re.search(r'"([^"]*)"', text)
            if not match:
                self._track(start_t, ok=True)
                return {}
            fields = match.group(1).split(",")
            if len(fields) < 10:
                self._track(start_t, ok=True)
                return {}
            name = fields[0]
            prev_close = _safe_float(fields[2])
            price = _safe_float(fields[3])
            high = _safe_float(fields[4])
            low = _safe_float(fields[5])
            volume = _safe_float(fields[8])
            amount = _safe_float(fields[9])
            change_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close else 0.0
            result = {
                "name": name,
                "price": price,
                "prev_close": prev_close,
                "high": high,
                "low": low,
                "volume": volume,
                "amount": amount,
                "change_pct": change_pct,
            }
            self._spot_cache[cache_key] = result
            self._spot_cache_ts = now
            self._track(start_t, ok=True)
            return result
        except Exception as exc:  # noqa: BLE001
            logger.warning("[SinaTencent] 实时报价失败 %s: %s", ticker, exc)
            self._track(start_t, ok=False)
            return {}

    def get_batch_realtime_quotes(self, tickers: List[str]) -> Dict[str, Dict[str, Any]]:
        """新浪支持批量查询：一次请求多只票（逗号分隔）。"""
        if not tickers:
            return {}
        symbols = [_sina_symbol(re.sub(r"[^\d]", "", t)) for t in tickers]
        url = f"http://hq.sinajs.cn/list={','.join(symbols)}"
        result: Dict[str, Dict[str, Any]] = {}
        try:
            text = _http_get(url, headers={"Referer": "https://finance.sina.com.cn/"})
            for ticker, symbol in zip(tickers, symbols):
                # 提取该 symbol 的数据行
                pattern = rf'hq_str_{re.escape(symbol)}="([^"]*)"'
                m = re.search(pattern, text)
                if not m:
                    continue
                fields = m.group(1).split(",")
                if len(fields) < 10:
                    continue
                prev_close = _safe_float(fields[2])
                price = _safe_float(fields[3])
                result[ticker] = {
                    "name": fields[0],
                    "price": price,
                    "change_pct": round((price - prev_close) / prev_close * 100, 2) if prev_close else 0.0,
                }
            return result
        except Exception as exc:  # noqa: BLE001
            logger.warning("[SinaTencent] 批量报价失败: %s", exc)
            return result

    # -------------------------
    # 历史日K线（腾讯）
    # -------------------------
    def get_historical_kline(self, ticker: str, limit: int = 100) -> pd.DataFrame:
        """腾讯日K接口：返回日K（不复权），字段 date/open/high/low/close/volume。

        接口：proxy.finance.qq.com/ifzqgtimg/appstock/app/kline/kline
        返回格式：data.{symbol}.day = [[date, open, close, high, low, volume], ...]
        """
        numeric = re.sub(r"[^\d]", "", ticker)
        cache_key = f"tencent_hist_{numeric}"
        now = time.time()
        cached = self._cache.get(cache_key)
        if cached and (now - cached["time"] < self.HIST_TTL):
            return cached["data"]

        start_t = time.time()
        symbol = _tencent_symbol(numeric)
        count = min(max(limit, 30), 320)
        # 腾讯日K接口（kline/kline，不复权）。count 控制返回根数。
        url = f"http://proxy.finance.qq.com/ifzqgtimg/appstock/app/kline/kline?param={symbol},day,,,{count}"
        try:
            text = _http_get(url)
            import json

            payload = json.loads(text)
            if payload.get("code") != 0:
                self._track(start_t, ok=True)
                return pd.DataFrame()
            data_node = (
                payload.get("data", {}).get(symbol, {})
                if isinstance(payload.get("data"), dict)
                else {}
            )
            # 接口返回 key 为 "day"（不复权）
            rows = data_node.get("day") or data_node.get("qfqday") or []
            if not rows:
                self._track(start_t, ok=True)
                return pd.DataFrame()
            # 每行：[date, open, close, high, low, volume, ...]
            records = []
            for r in rows:
                if len(r) < 6:
                    continue
                records.append({
                    "date": str(r[0]),
                    "open": _safe_float(r[1]),
                    "high": _safe_float(r[3]),
                    "low": _safe_float(r[4]),
                    "close": _safe_float(r[2]),
                    "volume": _safe_float(r[5]),
                })
            df = pd.DataFrame(records)
            if df.empty:
                self._track(start_t, ok=True)
                return pd.DataFrame()
            df = df.tail(limit).reset_index(drop=True)
            self._cache[cache_key] = {"time": now, "data": df}
            self._track(start_t, ok=True)
            return df
        except Exception as exc:  # noqa: BLE001
            logger.warning("[SinaTencent] 日K拉取失败 %s: %s", ticker, exc)
            self._track(start_t, ok=False)
            return pd.DataFrame()


def _safe_float(value: Any) -> float:
    try:
        if value is None or value == "":
            return 0.0
        result = float(value)
        return result if result == result else 0.0
    except (TypeError, ValueError):
        return 0.0
