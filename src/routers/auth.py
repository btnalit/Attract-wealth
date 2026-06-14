"""
来财 (Attract-wealth) — API 鉴权依赖。

设计目标：
- 默认向后兼容：未配置 API_KEY 时鉴权关闭（开发/测试场景不破坏现有行为）。
- 生产环境必须显式设置环境变量 API_KEY 并启用 API_AUTH_ENABLED=true。
- 支持 Authorization: Bearer <key> 和 X-API-Key: <key> 两种头格式。
- 提供专用的敏感端点鉴权依赖（下单/撤单/切通道等）。

注意：本模块仅做静态 API Key 校验。如需细粒度权限/用户体系，请在此扩展。
"""
from __future__ import annotations

import logging
import os
import secrets
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader

from src.core.errors import error_response

logger = logging.getLogger(__name__)

# 支持两种常见的 API Key 头格式
_BEARER_HEADER = APIKeyHeader(name="Authorization", auto_error=False, scheme_name="Bearer")
_X_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def _is_truthy(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _auth_enabled() -> bool:
    """鉴权是否启用。

    启用条件（任一）：
    1. 显式设置 API_AUTH_ENABLED=true
    2. 设置了 API_KEY（非空）

    这样部署者只要设了 API_KEY，鉴权就自动生效，避免"设了密钥却忘了开开关"的疏漏。
    """
    if _is_truthy(os.getenv("API_AUTH_ENABLED"), default=False):
        return True
    return bool(os.getenv("API_KEY", "").strip())


def _configured_key() -> str:
    return os.getenv("API_KEY", "").strip()


def _extract_provided_key(bearer_value: str | None, x_api_key_value: str | None) -> str:
    """从请求头提取调用方提供的 key，兼容 Bearer / X-API-Key 两种格式。"""
    if x_api_key_value:
        return x_api_key_value.strip()
    if bearer_value:
        text = bearer_value.strip()
        # 兼容 "Bearer xxx" 和裸 "xxx"
        if text.lower().startswith("bearer "):
            return text[7:].strip()
        return text
    return ""


def _reject(message: str, *, auth_header: str = "Bearer") -> HTTPException:
    """统一构造 401 响应。"""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=error_response("UNAUTHORIZED", message, {"auth_header": auth_header}),
        headers={"WWW-Authenticate": auth_header},
    )


async def require_api_key(
    request: Request,
    bearer_value: str | None = Depends(_BEARER_HEADER),
    x_api_key_value: str | None = Depends(_X_API_KEY_HEADER),
) -> dict[str, Any]:
    """通用 API Key 鉴权依赖。

    返回调用方上下文（供日志/审计使用）。鉴权关闭时返回匿名上下文。

    使用方式（在路由中）::

        from src.routers.auth import require_api_key
        @router.post("/sensitive", dependencies=[Depends(require_api_key)])
        async def handler(...): ...
    """
    if not _auth_enabled():
        # 鉴权关闭（开发/测试默认）。记录一次警告，提示生产应启用。
        if not getattr(require_api_key, "_warned", False):
            logger.warning(
                "API auth is DISABLED. Set API_KEY + API_AUTH_ENABLED=true in production."
            )
            setattr(require_api_key, "_warned", True)
        return {"authenticated": False, "principal": "anonymous", "auth_disabled": True}

    configured = _configured_key()
    provided = _extract_provided_key(bearer_value, x_api_key_value)

    if not provided:
        raise _reject("missing API key (Authorization: Bearer <key> or X-API-Key)")
    if not secrets.compare_digest(provided, configured):
        # 常量时间比较，避免时序侧信道
        raise _reject("invalid API key")

    return {"authenticated": True, "principal": "api-client", "auth_disabled": False}


# 专用于"会动钱"的敏感端点的强鉴权依赖。
# 即使整体 auth 关闭，也强烈建议这些端点保持受控；当前实现仍遵循 _auth_enabled，
# 但留作后续强制鉴权的扩展点。
require_api_key_strict = require_api_key


async def require_api_key_query(request: Request) -> dict[str, Any]:
    """从 query param 读取 API Key 的鉴权依赖。

    专用于 EventSource/SSE 端点（浏览器 EventSource 不支持自定义 header）。
    优先级：query param `api_key` > Authorization header > X-API-Key header。

    安全权衡：query param 会出现在 URL/访问日志中，安全性低于 header，
    仅用于 EventSource 等无法设置 header 的场景。生产环境建议配合 HTTPS 使用。
    """
    if not _auth_enabled():
        if not getattr(require_api_key_query, "_warned", False):
            logger.warning(
                "API auth is DISABLED. Set API_KEY + API_AUTH_ENABLED=true in production."
            )
            setattr(require_api_key_query, "_warned", True)
        return {"authenticated": False, "principal": "anonymous", "auth_disabled": True}

    configured = _configured_key()
    # 1. query param（EventSource 主路径）
    provided = (request.query_params.get("api_key") or "").strip()
    # 2. 回退到 header（兼容非 EventSource 客户端访问同一端点）
    if not provided:
        bearer = request.headers.get("Authorization", "").strip()
        if bearer.lower().startswith("bearer "):
            provided = bearer[7:].strip()
        else:
            provided = request.headers.get("X-API-Key", "").strip()

    if not provided:
        raise _reject("missing API key (api_key query param, Authorization, or X-API-Key)")
    if not secrets.compare_digest(provided, configured):
        raise _reject("invalid API key")

    return {"authenticated": True, "principal": "api-client", "auth_disabled": False}
