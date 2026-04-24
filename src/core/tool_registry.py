"""Unified tool registry with permission and hook governance."""
from __future__ import annotations

import inspect
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel, ValidationError
from src.core.hooks import HookManager
from src.core.permissions import PermissionGuard


ToolHandler = Callable[[dict[str, Any]], Any]


@dataclass
class ToolSpec:
    """Registered tool specification."""

    name: str
    handler: ToolHandler
    description: str = ""
    tags: list[str] = field(default_factory=list)
    input_model: type[BaseModel] | None = None
    example_payload: dict[str, Any] = field(default_factory=dict)


class ToolRegistry:
    """Registry that enforces permission and lifecycle hooks on tool execution."""

    def __init__(
        self,
        *,
        permission_guard: PermissionGuard | None = None,
        hook_manager: HookManager | None = None,
    ) -> None:
        self.permission_guard = permission_guard
        self.hook_manager = hook_manager
        self._tools: dict[str, ToolSpec] = {}
        self._stats: dict[str, dict[str, Any]] = {}

    def register(
        self,
        *,
        name: str,
        handler: ToolHandler,
        description: str = "",
        tags: list[str] | None = None,
        input_model: type[BaseModel] | None = None,
        example_payload: dict[str, Any] | None = None,
    ) -> None:
        """Register one tool handler."""
        normalized = str(name or "").strip().lower()
        if not normalized:
            raise ValueError("tool name is required")
        self._tools[normalized] = ToolSpec(
            name=normalized,
            handler=handler,
            description=str(description or ""),
            tags=[str(item) for item in (tags or [])],
            input_model=input_model,
            example_payload=dict(example_payload or {}),
        )
        self._stats.setdefault(
            normalized,
            {
                "calls": 0,
                "success": 0,
                "failed": 0,
                "last_error": "",
                "last_called_at": 0.0,
                "last_duration_ms": 0.0,
            },
        )

    def list_tools(self) -> list[dict[str, Any]]:
        """List registered tools."""
        items: list[dict[str, Any]] = []
        for name, spec in sorted(self._tools.items()):
            stat = dict(self._stats.get(name, {}))
            items.append(
                {
                    "name": name,
                    "description": spec.description,
                    "tags": list(spec.tags),
                    "input_model": spec.input_model.__name__ if spec.input_model is not None else "",
                    "input_schema": (
                        spec.input_model.model_json_schema()
                        if spec.input_model is not None
                        else {}
                    ),
                    "example_payload": dict(spec.example_payload),
                    "stats": stat,
                }
            )
        return items

    async def execute(self, name: str, payload: dict[str, Any] | None = None, *, actor: str = "system") -> Any:
        """Execute a tool through governance pipeline."""
        normalized = str(name or "").strip().lower()
        if normalized not in self._tools:
            raise KeyError(f"tool not found: {normalized}")

        started = time.time()
        body = dict(payload or {})
        stat = self._stats.setdefault(
            normalized,
            {"calls": 0, "success": 0, "failed": 0, "last_error": "", "last_called_at": 0.0, "last_duration_ms": 0.0},
        )
        stat["calls"] = int(stat.get("calls", 0)) + 1
        stat["last_called_at"] = started

        spec = self._tools[normalized]
        decision = (
            self.permission_guard.check_tool(normalized, actor=actor, payload=body)
            if self.permission_guard is not None
            else None
        )
        if decision is not None and not decision.allowed:
            duration_ms = (time.time() - started) * 1000.0
            stat["failed"] = int(stat.get("failed", 0)) + 1
            stat["last_error"] = decision.reason
            stat["last_duration_ms"] = round(duration_ms, 3)
            if self.hook_manager is not None:
                await self.hook_manager.emit(
                    "tool_permission_denied",
                    {
                        "tool": normalized,
                        "actor": actor,
                        "reason": decision.reason,
                        "metadata": dict(decision.metadata),
                    },
                )
            raise PermissionError(f"tool denied: {normalized} ({decision.reason})")

        if spec.input_model is not None:
            try:
                validated = spec.input_model.model_validate(body)
                body = validated.model_dump()
            except ValidationError as exc:
                duration_ms = (time.time() - started) * 1000.0
                stat["failed"] = int(stat.get("failed", 0)) + 1
                stat["last_error"] = f"validation_error: {str(exc)}"
                stat["last_duration_ms"] = round(duration_ms, 3)
                if self.hook_manager is not None:
                    await self.hook_manager.emit(
                        "tool_validation_error",
                        {
                            "tool": normalized,
                            "actor": actor,
                            "error": str(exc),
                        },
                    )
                raise ValueError(f"tool input validation failed: {normalized}") from exc

        if self.hook_manager is not None:
            await self.hook_manager.emit("tool_pre", {"tool": normalized, "actor": actor, "payload": dict(body)})

        try:
            result = spec.handler(dict(body))
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:  # noqa: BLE001
            duration_ms = (time.time() - started) * 1000.0
            stat["failed"] = int(stat.get("failed", 0)) + 1
            stat["last_error"] = str(exc)
            stat["last_duration_ms"] = round(duration_ms, 3)
            if self.hook_manager is not None:
                await self.hook_manager.emit(
                    "tool_error",
                    {
                        "tool": normalized,
                        "actor": actor,
                        "error": str(exc),
                    },
                )
            raise

        duration_ms = (time.time() - started) * 1000.0
        stat["success"] = int(stat.get("success", 0)) + 1
        stat["last_error"] = ""
        stat["last_duration_ms"] = round(duration_ms, 3)
        if self.hook_manager is not None:
            await self.hook_manager.emit(
                "tool_post",
                {
                    "tool": normalized,
                    "actor": actor,
                    "duration_ms": round(duration_ms, 3),
                    "result_type": type(result).__name__,
                },
            )
        return result

    def snapshot(self) -> dict[str, Any]:
        """Return registry snapshot for runtime API."""
        return {
            "tool_count": len(self._tools),
            "tools": self.list_tools(),
        }
