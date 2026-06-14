# -*- coding: utf-8 -*-
"""
数据流标准接口定义层 (Data Interface)
源自: TradingAgents-CN 原版 `dataflows/interface.py`
作用: 通过 Protocol 和抽象类制定取数规约，使上层智能体和技术工厂不用关心数据到底是来自 akshare 还是 tushare。
"""
from typing import Dict, Any, List
try:
    from typing import Protocol
except ImportError:
    from typing_extensions import Protocol  # type: ignore
import pandas as pd


class DataProvider(Protocol):
    """底层提供商应该实现的取数接口（基础三件套）"""

    def get_realtime_quote(self, ticker: str) -> Dict[str, Any]:
        """获取极少量的单票最新行情 (Price, Volume, Change)"""
        ...

    def get_historical_kline(self, ticker: str, limit: int = 100) -> pd.DataFrame:
        """获取用于算均线的日K线历史大全 (Open, High, Low, Close, Volume)"""
        ...

    def get_batch_realtime_quotes(self, tickers: List[str]) -> Dict[str, Dict[str, Any]]:
        """批量获取多只票的实时盘口 (解决循环请求防查水表)"""
        ...


class AShareExtendedProvider(Protocol):
    """
    A 股衍生数据接口（龙虎榜/资金流/板块/财务/融券/风险标记）。

    这一组是 A 股分析增强引入的扩展契约。所有方法必须"软失败"：
    拿不到数据时返回空 dict / 空 list，**绝不抛异常**，保证单点失败
    不阻断整个 analyze 链路。各 Provider 可按自身能力选择性实现，
    未实现的维度由 DefaultAShareExtendedMixin 提供空默认值。
    """

    def get_dragon_tiger(self, ticker: str) -> List[Dict[str, Any]]:
        """龙虎榜：近 N 日上榜明细（营业部/机构席位/买卖净额）。"""
        ...

    def get_money_flow(self, ticker: str) -> Dict[str, Any]:
        """个股资金流向：主力净流入、超大/大/中/小单分解（近 N 日）。"""
        ...

    def get_sector_info(self, ticker: str) -> Dict[str, Any]:
        """所属行业/概念板块 + 板块当日涨跌幅 + 板块资金流排名。"""
        ...

    def get_financial_abstract(self, ticker: str) -> Dict[str, Any]:
        """财务摘要：PE/PB/ROE/营收/净利润/毛利率等核心指标。"""
        ...

    def get_margin(self, ticker: str) -> Dict[str, Any]:
        """融资融券：融资余额、融券余额、近 N 日变化。"""
        ...

    def get_stock_flags(self, ticker: str) -> Dict[str, Any]:
        """A 股风险/状态标记：ST/退市风险/停牌/涨跌停状态。"""
        ...

    def get_announcements(self, ticker: str, limit: int = 10) -> List[Dict[str, Any]]:
        """个股公告：重大事项、业绩预告、增减持等结构化公告。"""
        ...


class DefaultAShareExtendedMixin:
    """
    A 股扩展接口的空默认实现混入基类。

    Provider 只需继承本类 + 选择性覆盖能实现的方法，即可同时满足
    `AShareExtendedProvider` 契约，未实现的维度自动返回空值（软失败）。
    这样既保证接口完整，又不强迫每个 provider 实现全部 6 个方法。
    """

    def get_dragon_tiger(self, ticker: str) -> List[Dict[str, Any]]:  # noqa: ARG002
        return []

    def get_money_flow(self, ticker: str) -> Dict[str, Any]:  # noqa: ARG002
        return {}

    def get_sector_info(self, ticker: str) -> Dict[str, Any]:  # noqa: ARG002
        return {}

    def get_financial_abstract(self, ticker: str) -> Dict[str, Any]:  # noqa: ARG002
        return {}

    def get_margin(self, ticker: str) -> Dict[str, Any]:  # noqa: ARG002
        return {}

    def get_stock_flags(self, ticker: str) -> Dict[str, Any]:  # noqa: ARG002
        return {}

    def get_announcements(self, ticker: str, limit: int = 10) -> List[Dict[str, Any]]:  # noqa: ARG002
        return []


class IndicatorEngine(Protocol):
    """算法引擎的标准入料加工接口"""

    def calculate_all(self, df: pd.DataFrame) -> pd.DataFrame:
        """接收清洗好的 OHLCV，吐出带有 MACD拉链、RSI 的 DataFrame"""
        ...


def has_extended_provider(obj: object) -> bool:
    """快速判断一个对象是否暴露 A 股扩展接口方法（用 hasattr 逐个检测）。"""
    return all(
        hasattr(obj, method)
        for method in (
            "get_dragon_tiger",
            "get_money_flow",
            "get_sector_info",
            "get_financial_abstract",
            "get_margin",
            "get_stock_flags",
        )
    )
