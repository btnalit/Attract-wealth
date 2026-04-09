# -*- coding: utf-8 -*-
"""
来财 — MCP Client

用于连接到本地或远程 MCP Server，调用金融工具。
"""
from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


class MCPClient:
    """MCP Client — 连接到 MCP Server 并调用工具"""

    def __init__(self, base_url: str = "http://127.0.0.1:8765"):
        self.base_url = base_url.rstrip("/")
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def list_tools(self) -> list[dict[str, Any]]:
        """列出 Server 上的可用工具"""
        response = await self._jsonrpc_request({"method": "tools/list"})
        result = response.get("result", {})
        return result.get("tools", [])

    async def call_tool(self, tool_name: str, arguments: dict | None = None) -> Any:
        """调用指定工具"""
        params = {"name": tool_name, "arguments": arguments or {}}
        response = await self._jsonrpc_request({"method": "tools/call", "params": params})
        result = response.get("result", {})
        content_list = result.get("content", [])
        if content_list:
            text = content_list[0].get("text", "")
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
        return result

    async def _jsonrpc_request(self, body: dict) -> dict:
        session = await self._get_session()
        body.setdefault("jsonrpc", "2.0")
        body.setdefault("id", "client-1")

        try:
            async with session.post(f"{self.base_url}/mcp", json=body) as resp:
                resp.raise_for_status()
                return await resp.json()
        except aiohttp.ClientError as exc:
            logger.error("MCP request failed: %s", exc)
            raise
        finally:
            pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()


# --- CLI Demo ---
async def demo():
    async with MCPClient() as client:
        tools = await client.list_tools()
        print(f"Available tools: {[t['name'] for t in tools]}")

        # 调用示例
        result = await client.call_tool("get_stock_quote", {"ticker": "sh600000"})
        print(f"Quote result: {result}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import asyncio
    asyncio.run(demo())
