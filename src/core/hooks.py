"""Lifecycle hook manager for core governance."""
from __future__ import annotations

import inspect
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable


HookHandler = Callable[[dict[str, Any]], Any]


@dataclass
class HookEvent:
    """Hook execution event."""

    phase: str
    name: str
    status: str
    at_ts: float
    duration_ms: float
    detail: str


class HookManager:
    """Manage lifecycle hooks and record execution traces."""

    def __init__(self, *, max_recent_events: int = 40) -> None:
        self._handlers: dict[str, list[tuple[str, HookHandler]]] = {}
        self._recent_events: deque[HookEvent] = deque(maxlen=max(1, int(max_recent_events)))
        self._phase_counts: dict[str, int] = {}
        self._events_total = 0
        self._errors_total = 0

    def register(self, phase: str, handler: HookHandler, *, name: str = "") -> str:
        """Register hook handler to a phase."""
        phase_text = str(phase or "").strip().lower()
        if not phase_text:
            raise ValueError("phase is required")
        handler_name = str(name or getattr(handler, "__name__", "anonymous_hook")).strip() or "anonymous_hook"
        self._handlers.setdefault(phase_text, []).append((handler_name, handler))
        return handler_name

    async def emit(self, phase: str, payload: dict[str, Any] | None = None) -> list[HookEvent]:
        """Emit a phase event and execute all handlers."""
        phase_text = str(phase or "").strip().lower()
        handlers = list(self._handlers.get(phase_text, []))
        if not handlers:
            return []

        events: list[HookEvent] = []
        body = dict(payload or {})
        for handler_name, handler in handlers:
            started = time.time()
            status = "ok"
            detail = ""
            try:
                result = handler(dict(body))
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:  # noqa: BLE001
                status = "error"
                detail = str(exc)
                self._errors_total += 1
            duration_ms = (time.time() - started) * 1000.0
            event = HookEvent(
                phase=phase_text,
                name=handler_name,
                status=status,
                at_ts=started,
                duration_ms=round(duration_ms, 3),
                detail=detail,
            )
            events.append(event)
            self._recent_events.append(event)
            self._events_total += 1
            self._phase_counts[phase_text] = int(self._phase_counts.get(phase_text, 0)) + 1
        return events

    def snapshot(self) -> dict[str, Any]:
        """Return hook manager status for runtime API."""
        return {
            "registered_phases": {
                phase: [name for name, _handler in items]
                for phase, items in sorted(self._handlers.items())
            },
            "events_total": int(self._events_total),
            "errors_total": int(self._errors_total),
            "phase_counts": dict(self._phase_counts),
            "recent_events": [
                {
                    "phase": item.phase,
                    "name": item.name,
                    "status": item.status,
                    "at_ts": item.at_ts,
                    "duration_ms": item.duration_ms,
                    "detail": item.detail,
                }
                for item in list(self._recent_events)
            ],
        }
