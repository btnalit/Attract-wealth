# -*- coding: utf-8 -*-
"""
来财 (Attract-wealth) — MCP 协议支持 (Tool Registry & Server)

职责:
  - 将 TradingVM、Dataflows、Execution 层的功能包装为 MCP Tools
  - 提供 MCP Server 供外部客户端 (其他 Agent、第三方应用) 调用
  - 提供 MCP Client 用于连接到远程 MCP Server

使用方式:
  Server: python -m src.mcp.server
  Client: from src.mcp.client import MCPClient
"""
from __future__ import annotations
