# -*- coding: utf-8 -*-
"""
来财 — MCP Tools 注册表

将底层模块包装为 Pydantic Schema 定义的 MCP 可调用的工具。
"""
from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool Input/Output Schemas
# ---------------------------------------------------------------------------

class GetStockQuoteInput(BaseModel):
    ticker: str = Field(..., description="股票代码，如 sh600000 或 sz000001")


class GetStockQuoteOutput(BaseModel):
    ticker: str
    name: str
    price: float
    change_pct: float
    volume: float
    turnover: float
    timestamp: str


class GetKlineInput(BaseModel):
    ticker: str = Field(..., description="股票代码")
    interval: str = Field(default="daily", description="时间粒度: daily/weekly/monthly/30m/60m")
    limit: int = Field(default=100, description="返回条数")


class KlineBar(BaseModel):
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float


class GetKlineOutput(BaseModel):
    ticker: str
    interval: str
    bars: list[KlineBar]


class CalculateIndicatorsInput(BaseModel):
    ticker: str = Field(..., description="股票代码")


class CalculateIndicatorsOutput(BaseModel):
    ticker: str
    ma5: float | None = None
    ma10: float | None = None
    ma20: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    rsi: float | None = None
    boll_upper: float | None = None
    boll_lower: float | None = None


class SubmitOrderInput(BaseModel):
    ticker: str = Field(..., description="股票代码")
    side: str = Field(..., description="买卖方向: buy / sell")
    quantity: int = Field(..., description="数量 (股)")
    price: float = Field(..., description="委托价格")
    order_type: str = Field(default="limit", description="订单类型: limit / market")


class SubmitOrderOutput(BaseModel):
    order_id: str
    status: str
    message: str


class GetPortfolioOutput(BaseModel):
    total_value: float
    cash: float
    positions: list[dict[str, Any]]
    daily_pnl: float
    total_pnl: float


class TriggerReflectionInput(BaseModel):
    date: str = Field(default="", description="反思日期 YYYY-MM-DD，留空为当日")


class TriggerReflectionOutput(BaseModel):
    success: bool
    report_summary: str


# ---------------------------------------------------------------------------
# Tool Definitions
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "get_stock_quote",
        "description": "获取股票实时行情",
        "input_schema": GetStockQuoteInput.model_json_schema(),
    },
    {
        "name": "get_kline_data",
        "description": "获取股票历史 K 线数据",
        "input_schema": GetKlineInput.model_json_schema(),
    },
    {
        "name": "calculate_indicators",
        "description": "计算股票技术指标 (MA/MACD/RSI/BOLL)",
        "input_schema": CalculateIndicatorsInput.model_json_schema(),
    },
    {
        "name": "submit_order",
        "description": "提交交易订单 (模拟或实盘)",
        "input_schema": SubmitOrderInput.model_json_schema(),
    },
    {
        "name": "get_portfolio_status",
        "description": "获取当前持仓和资产状况",
        "input_schema": {},
    },
    {
        "name": "trigger_reflection",
        "description": "触发每日反思流程",
        "input_schema": TriggerReflectionInput.model_json_schema(),
    },
]


# ---------------------------------------------------------------------------
# Tool Handlers Registry
# ---------------------------------------------------------------------------

class ToolHandlers:
    """工具处理器注册表"""

    def __init__(self):
        self._handlers: dict[str, callable] = {}

    def register(self, name: str, handler: callable):
        self._handlers[name] = handler
        logger.info("Registered MCP tool: %s", name)

    def get(self, name: str) -> callable | None:
        return self._handlers.get(name)

    def list_tools(self) -> list[str]:
        return list(self._handlers.keys())


# --- 创建默认处理器工厂函数 ---

def create_default_handlers(
    data_interface: Any = None,
    trading_vm: Any = None,
    reflector: Any = None,
) -> ToolHandlers:
    """创建默认工具处理器"""
    handlers = ToolHandlers()

    async def _get_stock_quote(ticker: str, **kwargs) -> dict:
        if data_interface is None:
            return {"error": "DataInterface not configured"}
        try:
            quote = await data_interface.get_realtime_quote([ticker])
            return quote[0] if quote else {"error": f"No quote for {ticker}"}
        except Exception as exc:
            logger.error("get_stock_quote failed: %s", exc)
            return {"error": str(exc)}

    async def _get_kline_data(ticker: str, interval: str = "daily", limit: int = 100, **kwargs) -> dict:
        if data_interface is None:
            return {"error": "DataInterface not configured"}
        try:
            kline = await data_interface.get_historical_kline(ticker, interval, limit)
            return {"ticker": ticker, "interval": interval, "bars": kline or []}
        except Exception as exc:
            logger.error("get_kline_data failed: %s", exc)
            return {"error": str(exc)}

    async def _calculate_indicators(ticker: str, **kwargs) -> dict:
        if data_interface is None:
            return {"error": "DataInterface not configured"}
        try:
            indicators = await data_interface.get_indicators(ticker)
            return {"ticker": ticker, **indicators}
        except Exception as exc:
            logger.error("calculate_indicators failed: %s", exc)
            return {"error": str(exc)}

    async def _submit_order(ticker: str, side: str, quantity: int, price: float,
                           order_type: str = "limit", **kwargs) -> dict:
        if trading_vm is None:
            return {"error": "TradingVM not configured"}
        try:
            result = await trading_vm.execute_order(
                ticker=ticker, side=side, quantity=quantity, price=price, order_type=order_type
            )
            return {"order_id": result.get("id", ""), "status": result.get("status", "submitted"), "message": "OK"}
        except Exception as exc:
            logger.error("submit_order failed: %s", exc)
            return {"error": str(exc)}

    async def _get_portfolio_status(**kwargs) -> dict:
        if trading_vm is None:
            return {"error": "TradingVM not configured"}
        try:
            return await trading_vm.get_portfolio()
        except Exception as exc:
            logger.error("get_portfolio_status failed: %s", exc)
            return {"error": str(exc)}

    async def _trigger_reflection(date: str = "", **kwargs) -> dict:
        if reflector is None:
            return {"error": "Reflector not configured"}
        try:
            report = await reflector.daily_reflection(date=date)
            return {"success": True, "report_summary": str(report)}
        except Exception as exc:
            logger.error("trigger_reflection failed: %s", exc)
            return {"error": str(exc)}

    handlers.register("get_stock_quote", _get_stock_quote)
    handlers.register("get_kline_data", _get_kline_data)
    handlers.register("calculate_indicators", _calculate_indicators)
    handlers.register("submit_order", _submit_order)
    handlers.register("get_portfolio_status", _get_portfolio_status)
    handlers.register("trigger_reflection", _trigger_reflection)

    return handlers
