# -*- coding: utf-8 -*-
"""
来财 — MCP Server

使用 JSON-RPC 2.0 协议提供 MCP Server，
供外部 Agent 或第三方应用调用金融工具。
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from src.mcp.tools import TOOL_DEFINITIONS, create_default_handlers

logger = logging.getLogger(__name__)


class MCPServer:
    """MCP JSON-RPC 2.0 Server"""

    def __init__(self, host: str = "127.0.0.1", port: int = 8765):
        self.host = host
        self.port = port
        self._handlers = None
        self._running = False

    def set_handlers(self, handlers):
        """设置工具处理器"""
        self._handlers = handlers

    def setup_default(self, data_interface=None, trading_vm=None, reflector=None):
        """使用默认处理器设置"""
        self._handlers = create_default_handlers(
            data_interface=data_interface,
            trading_vm=trading_vm,
            reflector=reflector,
        )

    def list_tools(self) -> list[dict[str, Any]]:
        """列出所有可用工具"""
        return TOOL_DEFINITIONS

    async def handle_request(self, request: dict) -> dict:
        """处理单个 JSON-RPC 请求"""
        method = request.get("method")
        params = request.get("params", {})
        request_id = request.get("id", str(uuid.uuid4()))

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"tools": self.list_tools()},
            }

        if method == "tools/call":
            tool_name = params.get("name")
            tool_args = params.get("arguments", {})
            return await self._handle_tool_call(request_id, tool_name, tool_args)

        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }

    async def _handle_tool_call(self, request_id: str, tool_name: str, tool_args: dict) -> dict:
        if self._handlers is None:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32603, "message": "No handlers configured"},
            }

        handler = self._handlers.get(tool_name)
        if handler is None:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": f"Tool not found: {tool_name}"},
            }

        try:
            result = await handler(**tool_args)
            content = json.dumps(result, ensure_ascii=False) if isinstance(result, dict) else str(result)
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [{"type": "text", "text": content}],
                    "isError": "error" in result if isinstance(result, dict) else False,
                },
            }
        except Exception as exc:
            logger.error("Tool call failed: %s(%s) → %s", tool_name, tool_args, exc)
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32603, "message": f"Internal error: {exc}"},
            }

    async def start_sse(self):
        """启动 SSE (Server-Sent Events) 服务"""
        from aiohttp import web

        async def handle_post(request):
            body = await request.json()
            response = await self.handle_request(body)
            return web.json_response(response)

        async def handle_sse(request):
            """SSE 端点 — 仅用于推送事件，不接收调用"""
            try:
                from aiohttp_sse import sse_response
                async with sse_response(request) as resp:
                    self._running = True
                    logger.info("SSE client connected")
                    try:
                        while self._running:
                            await asyncio.sleep(1)
                    except asyncio.CancelledError:
                        pass
                    return resp
            except ImportError:
                return web.Response(text="aiohttp-sse not installed", status=501)

        app = web.Application()
        app.router.add_post("/mcp", handle_post)
        app.router.add_get("/events", handle_sse)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()
        logger.info("MCP SSE Server started at http://%s:%d", self.host, self.port)
        return runner

    async def stop(self):
        self._running = False
        logger.info("MCP Server stopped")


# --- CLI Entry Point ---
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    server = MCPServer()
    server.setup_default()
    loop = asyncio.get_event_loop()
    try:
        runner = loop.run_until_complete(server.start_sse())
        loop.run_forever()
    except KeyboardInterrupt:
        loop.run_until_complete(server.stop())
