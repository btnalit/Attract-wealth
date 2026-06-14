# -*- coding: utf-8 -*-
"""
来财 (Attract-wealth) — 实时 SSE 事件流路由
支持 T-18 (SSE 客户端) 和 T-24 (实时日志终端)。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import AsyncGenerator
from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from src.routers.auth import require_api_key_query

logger = logging.getLogger(__name__)
router = APIRouter()

# 事件队列订阅中心
class EventBus:
    def __init__(self):
        self.subscribers: list[asyncio.Queue] = []

    def subscribe(self) -> asyncio.Queue:
        queue = asyncio.Queue()
        self.subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue):
        if queue in self.subscribers:
            self.subscribers.remove(queue)

    def publish(self, event_type: str, data: dict):
        message = json.dumps({
            "type": event_type,
            "timestamp": time.time(),
            "data": data
        }, ensure_ascii=False)
        for queue in self.subscribers:
            queue.put_nowait(message)

# 全局总线实例
event_bus = EventBus()

async def event_generator(request: Request, queue: asyncio.Queue) -> AsyncGenerator[str, None]:
    """SSE 生成器"""
    try:
        while True:
            # 检查客户端是否断开
            if await request.is_disconnected():
                break
            
            try:
                # 等待新事件，超时 10 秒发送心跳
                message = await asyncio.wait_for(queue.get(), timeout=10.0)
                yield message
            except asyncio.TimeoutError:
                # 发送 Keep-alive
                yield json.dumps({"type": "ping", "timestamp": time.time()})
                
    except asyncio.CancelledError:
        pass
    finally:
        event_bus.unsubscribe(queue)

@router.get("/events", dependencies=[Depends(require_api_key_query)])
async def sse_events(request: Request):
    """
    统一 SSE 流端点 (T-18 / T-24)
    消息类型: agent_start, agent_end, node_transition, log_message, trade_update
    """
    queue = event_bus.subscribe()
    return EventSourceResponse(event_generator(request, queue))

# ---------------------------------------------------------------------------
# 后端推流 API (供后端其他组件调用)
# ---------------------------------------------------------------------------

def publish_log(agent_name: str, message: str, level: str = "info"):
    """推送日志到前端 (T-24)。

    字段统一用 camelCase（nodeId/message/level），与前端 useSSE 期望一致，
    消除前端 `agent ?? node_id ?? agent_name` 的兼容回退。
    同时保留 agent 字段做向后兼容。
    """
    event_bus.publish("log_message", {
        "nodeId": agent_name,
        "agent": agent_name,  # 向后兼容
        "message": message,
        "level": level,
    })

def publish_node_transition(node_id: str, status: str, payload: dict = None):
    """推送 LangGraph 节点跳转 (T-17)。

    字段统一用 camelCase（nodeId/status/payload），与前端期望一致。
    同时保留 node_id 做向后兼容。
    """
    event_bus.publish("node_transition", {
        "nodeId": node_id,
        "node_id": node_id,  # 向后兼容
        "status": status,  # active, completed, error
        "payload": payload or {}
    })

def publish_trade(ticker: str, side: str, price: float, quantity: int):
    """推送成交回报 (T-22)"""
    event_bus.publish("trade_update", {
        "ticker": ticker,
        "side": side,
        "price": price,
        "quantity": quantity
    })
