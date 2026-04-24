"""Coordinator for bounded parallel task execution."""
from __future__ import annotations

import asyncio
import inspect
import time
from typing import Any, Awaitable, Callable


Worker = Callable[[Any], Any]


class AgentCoordinator:
    """Bounded async coordinator with execution metrics."""

    def __init__(self) -> None:
        self._stats: dict[str, Any] = {
            "runs": 0,
            "tasks_total": 0,
            "ok": 0,
            "error": 0,
            "timeout": 0,
            "last_run_at": 0.0,
            "last_duration_ms": 0.0,
        }

    async def run_batch(
        self,
        items: list[Any],
        worker: Worker,
        *,
        max_concurrency: int = 5,
        timeout_s: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Run worker for each item with bounded concurrency."""
        started = time.time()
        semaphore = asyncio.Semaphore(max(1, int(max_concurrency)))
        results: list[dict[str, Any]] = [{"status": "pending", "result": None} for _ in items]

        async def _run_one(index: int, item: Any) -> None:
            async with semaphore:
                try:
                    value = worker(item)
                    if inspect.isawaitable(value):
                        if timeout_s and timeout_s > 0:
                            value = await asyncio.wait_for(value, timeout=timeout_s)
                        else:
                            value = await value
                    results[index] = {"status": "ok", "result": value}
                except asyncio.TimeoutError:
                    results[index] = {"status": "timeout", "result": None}
                except Exception as exc:  # noqa: BLE001
                    results[index] = {"status": "error", "result": str(exc)}

        await asyncio.gather(*[_run_one(idx, item) for idx, item in enumerate(items)])
        self._update_stats(results, started)
        return results

    async def run_named(
        self,
        tasks: dict[str, Callable[[], Awaitable[Any] | Any]],
        *,
        timeout_s: float = 0.0,
    ) -> dict[str, dict[str, Any]]:
        """Run named tasks in parallel and return task-level statuses."""
        names = list(tasks.keys())
        fns = [tasks[name] for name in names]

        async def _worker(index: int) -> Any:
            fn = fns[index]
            value = fn()
            if inspect.isawaitable(value):
                if timeout_s and timeout_s > 0:
                    return await asyncio.wait_for(value, timeout=timeout_s)
                return await value
            return value

        batch = await self.run_batch(list(range(len(names))), _worker, max_concurrency=max(1, len(names)), timeout_s=timeout_s)
        return {name: batch[idx] for idx, name in enumerate(names)}

    def _update_stats(self, results: list[dict[str, Any]], started: float) -> None:
        duration_ms = (time.time() - started) * 1000.0
        ok_count = len([item for item in results if item.get("status") == "ok"])
        error_count = len([item for item in results if item.get("status") == "error"])
        timeout_count = len([item for item in results if item.get("status") == "timeout"])

        self._stats["runs"] = int(self._stats.get("runs", 0)) + 1
        self._stats["tasks_total"] = int(self._stats.get("tasks_total", 0)) + len(results)
        self._stats["ok"] = int(self._stats.get("ok", 0)) + ok_count
        self._stats["error"] = int(self._stats.get("error", 0)) + error_count
        self._stats["timeout"] = int(self._stats.get("timeout", 0)) + timeout_count
        self._stats["last_run_at"] = started
        self._stats["last_duration_ms"] = round(duration_ms, 3)

    def snapshot(self) -> dict[str, Any]:
        """Return coordinator stats."""
        return dict(self._stats)
