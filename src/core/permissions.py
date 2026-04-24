"""Core permission guard for tools and filesystem-like paths."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any


def _parse_csv(raw: str | None) -> tuple[str, ...]:
    values: list[str] = []
    for item in str(raw or "").split(","):
        text = item.strip().lower()
        if text:
            values.append(text)
    return tuple(sorted(set(values)))


def _resolve_path(path: str) -> str:
    try:
        return str(Path(path).expanduser().resolve())
    except Exception:
        return str(Path(path).expanduser())


def _parse_path_csv(raw: str | None) -> tuple[str, ...]:
    values: list[str] = []
    for item in str(raw or "").split(","):
        text = item.strip()
        if text:
            values.append(_resolve_path(text))
    return tuple(sorted(set(values)))


def _normalize_mode(raw: str | None) -> str:
    text = str(raw or "allow").strip().lower()
    return "deny" if text in {"deny", "block", "blocked", "false"} else "allow"


def _match_pattern(value: str, patterns: tuple[str, ...]) -> str:
    for pattern in patterns:
        if fnmatch(value, pattern):
            return pattern
    return ""


def _path_startswith(path: str, prefixes: tuple[str, ...]) -> str:
    normalized_path = str(path or "").lower()
    for prefix in prefixes:
        if normalized_path.startswith(str(prefix).lower()):
            return prefix
    return ""


@dataclass
class PermissionDecision:
    """Normalized permission decision payload."""

    allowed: bool
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)


class PermissionGuard:
    """Permission guard for core governance entrypoints."""

    def __init__(
        self,
        *,
        allowed_tools: set[str] | tuple[str, ...] | None = None,
        blocked_tools: set[str] | tuple[str, ...] | None = None,
        allowed_path_prefixes: tuple[str, ...] | None = None,
        blocked_path_prefixes: tuple[str, ...] | None = None,
        default_mode: str = "allow",
    ) -> None:
        self.default_mode = _normalize_mode(default_mode)
        self.allowed_tools = _parse_csv(",".join(str(item) for item in (allowed_tools or ())))
        self.blocked_tools = _parse_csv(",".join(str(item) for item in (blocked_tools or ())))
        self.allowed_path_prefixes = tuple(allowed_path_prefixes or ())
        self.blocked_path_prefixes = tuple(blocked_path_prefixes or ())

    @classmethod
    def from_env(cls) -> PermissionGuard:
        """Build guard from environment variables."""
        return cls(
            default_mode=os.getenv("CORE_PERMISSION_DEFAULT_MODE", "allow"),
            allowed_tools=_parse_csv(os.getenv("CORE_ALLOWED_TOOLS", "")),
            blocked_tools=_parse_csv(os.getenv("CORE_BLOCKED_TOOLS", "")),
            allowed_path_prefixes=_parse_path_csv(os.getenv("CORE_ALLOWED_PATH_PREFIXES", "")),
            blocked_path_prefixes=_parse_path_csv(os.getenv("CORE_BLOCKED_PATH_PREFIXES", "")),
        )

    def check_tool(
        self,
        tool_name: str,
        *,
        actor: str = "",
        payload: dict[str, Any] | None = None,
    ) -> PermissionDecision:
        """Check whether a tool can be executed."""
        normalized = str(tool_name or "").strip().lower()
        meta = {
            "tool_name": normalized,
            "actor": str(actor or "").strip(),
            "payload_keys": sorted(list((payload or {}).keys())),
            "default_mode": self.default_mode,
        }
        if not normalized:
            return PermissionDecision(allowed=False, reason="empty_tool_name", metadata=meta)

        blocked_pattern = _match_pattern(normalized, self.blocked_tools)
        if blocked_pattern:
            return PermissionDecision(
                allowed=False,
                reason="blocked_tool_pattern",
                metadata={**meta, "matched_pattern": blocked_pattern},
            )

        if self.allowed_tools:
            allowed_pattern = _match_pattern(normalized, self.allowed_tools)
            if not allowed_pattern:
                return PermissionDecision(allowed=False, reason="not_in_allowed_tools", metadata=meta)
            return PermissionDecision(
                allowed=True,
                reason="allowed_tool_pattern",
                metadata={**meta, "matched_pattern": allowed_pattern},
            )

        if self.default_mode == "deny":
            return PermissionDecision(allowed=False, reason="default_deny_mode", metadata=meta)
        return PermissionDecision(allowed=True, reason="default_allow_mode", metadata=meta)

    def check_path(self, path: str, *, action: str = "read") -> PermissionDecision:
        """Check path access against allowlist/denylist prefixes."""
        resolved = _resolve_path(str(path or ""))
        meta = {
            "path": str(path or ""),
            "resolved_path": resolved,
            "action": str(action or "read"),
            "default_mode": self.default_mode,
        }

        blocked_prefix = _path_startswith(resolved, self.blocked_path_prefixes)
        if blocked_prefix:
            return PermissionDecision(
                allowed=False,
                reason="blocked_path_prefix",
                metadata={**meta, "matched_prefix": blocked_prefix},
            )

        if self.allowed_path_prefixes:
            allowed_prefix = _path_startswith(resolved, self.allowed_path_prefixes)
            if not allowed_prefix:
                return PermissionDecision(allowed=False, reason="path_not_in_allowlist", metadata=meta)
            return PermissionDecision(
                allowed=True,
                reason="allowed_path_prefix",
                metadata={**meta, "matched_prefix": allowed_prefix},
            )

        if self.default_mode == "deny":
            return PermissionDecision(allowed=False, reason="default_deny_mode", metadata=meta)
        return PermissionDecision(allowed=True, reason="default_allow_mode", metadata=meta)

    def snapshot(self) -> dict[str, Any]:
        """Return current guard configuration snapshot."""
        return {
            "default_mode": self.default_mode,
            "allowed_tools": list(self.allowed_tools),
            "blocked_tools": list(self.blocked_tools),
            "allowed_path_prefixes": list(self.allowed_path_prefixes),
            "blocked_path_prefixes": list(self.blocked_path_prefixes),
        }
