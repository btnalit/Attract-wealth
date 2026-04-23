# -*- coding: utf-8 -*-
"""
Event engine for scheduling autopilot tasks.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, List

from src.core.autopilot_templates import load_autopilot_templates
from src.core.system_store import SystemStore

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    HAS_APSCHEDULER = True
except ImportError:
    AsyncIOScheduler = None  # type: ignore[assignment]
    CronTrigger = None  # type: ignore[assignment]
    IntervalTrigger = None  # type: ignore[assignment]
    HAS_APSCHEDULER = False

logger = logging.getLogger(__name__)


class EventEngine:
    MANAGED_JOB_IDS = ("interval_polling", "tail_attack", "day_roll")

    def __init__(
        self,
        runner,
        execute_orders: bool = True,
        system_store: SystemStore | None = None,
        autopilot_templates: dict[str, dict[str, Any]] | None = None,
    ):
        self.runner = runner
        self.execute_orders = execute_orders
        self.system_store = system_store
        self.watchlists: List[str] = []
        self.autopilot_templates = autopilot_templates or load_autopilot_templates()
        self.active_template = ""
        if HAS_APSCHEDULER:
            self.scheduler = AsyncIOScheduler()
        else:
            self.scheduler = None
            logger.warning("apscheduler is not installed, scheduling is disabled")

    def start(self):
        if self.scheduler:
            self.scheduler.start()
            logger.info("EventEngine started")

    def stop(self):
        if self.scheduler:
            self.scheduler.shutdown()
            logger.info("EventEngine stopped")

    def load_watchlists(self, tickers: List[str], persist: bool = True, source: str = "manual") -> list[str]:
        normalized = SystemStore.normalize_tickers(tickers)
        self.watchlists = normalized
        if persist and self.system_store:
            self.system_store.save_watchlist(normalized, source=source)
        logger.info("watchlists updated: %s", self.watchlists)
        return self.get_watchlists()

    def restore_watchlists(self, fallback_tickers: List[str]) -> list[str]:
        if self.system_store:
            if self.system_store.watchlist_exists():
                saved = self.system_store.load_watchlist()
                self.watchlists = saved
                logger.info("watchlists restored from storage: %s", self.watchlists)
                return self.get_watchlists()
            return self.load_watchlists(fallback_tickers, persist=True, source="bootstrap")
        return self.load_watchlists(fallback_tickers, persist=False, source="bootstrap")

    def get_watchlists(self) -> list[str]:
        return list(self.watchlists)

    def add_tail_attack_trigger(self, hour: int = 14, minute: int = 45):
        if self.scheduler:
            self.scheduler.add_job(
                self._trigger_run_batch,
                self._build_cron_trigger(hour=hour, minute=minute),
                id="tail_attack",
                replace_existing=True,
                name="Daily Tail Attack Strategy",
            )
            logger.info("tail-attack trigger set at %02d:%02d", hour, minute)

    def add_interval_trigger(self, minutes: int):
        if self.scheduler:
            self.scheduler.add_job(
                self._trigger_run_batch,
                self._build_interval_trigger(minutes=minutes),
                id="interval_polling",
                replace_existing=True,
                name=f"Interval Polling ({minutes}m)",
            )
            logger.info("interval trigger set: every %d minutes", minutes)

    def add_day_roll_trigger(self, hour: int = 15, minute: int = 5):
        if self.scheduler:
            self.scheduler.add_job(
                self._trigger_day_roll,
                self._build_cron_trigger(hour=hour, minute=minute),
                id="day_roll",
                replace_existing=True,
                name="Daily Trading Day Roll",
            )
            logger.info("day-roll trigger set at %02d:%02d", hour, minute)

    def apply_autopilot_template(self, template_name: str, persist: bool = True) -> dict[str, Any]:
        key = str(template_name or "").strip().lower()
        template = self.autopilot_templates.get(key)
        if not template:
            raise ValueError(f"Unknown autopilot template: {template_name}")

        self._clear_managed_jobs()
        self.execute_orders = bool(template.get("execute_orders", self.execute_orders))

        schedule = template.get("schedule", {})
        interval = int(schedule.get("interval_minutes", 0) or 0)
        if interval > 0:
            self.add_interval_trigger(interval)

        tail_attack = str(schedule.get("tail_attack_time", "")).strip()
        if tail_attack:
            tail_time = self._parse_time(tail_attack)
            if tail_time:
                self.add_tail_attack_trigger(tail_time["hour"], tail_time["minute"])

        day_roll = str(schedule.get("day_roll_time", "")).strip()
        if day_roll:
            day_roll_time = self._parse_time(day_roll)
            if day_roll_time:
                self.add_day_roll_trigger(day_roll_time["hour"], day_roll_time["minute"])

        self.active_template = key
        if persist and self.system_store:
            self.system_store.set_autopilot_template(key)
        logger.info("autopilot template applied: %s", key)
        return self.get_autopilot_state()

    def get_autopilot_templates(self) -> dict[str, dict[str, Any]]:
        return {name: dict(template) for name, template in self.autopilot_templates.items()}

    def get_autopilot_state(self) -> dict[str, Any]:
        jobs: list[dict[str, Any]] = []
        if self.scheduler:
            for job in self.scheduler.get_jobs():
                if job.id not in self.MANAGED_JOB_IDS:
                    continue
                next_run_time = getattr(job, "next_run_time", None)
                next_run = next_run_time.isoformat() if next_run_time else ""
                jobs.append({"id": job.id, "next_run_time": next_run})
        return {
            "active_template": self.active_template,
            "execute_orders": self.execute_orders,
            "templates": list(self.autopilot_templates.keys()),
            "jobs": jobs,
        }

    def _clear_managed_jobs(self):
        if not self.scheduler:
            return
        for job_id in self.MANAGED_JOB_IDS:
            try:
                self.scheduler.remove_job(job_id)
            except Exception:
                continue

    @staticmethod
    def _build_interval_trigger(*, minutes: int):
        """
        Build interval trigger.
        In unit tests we may inject a fake scheduler even when apscheduler is absent.
        Returning a lightweight dict keeps add_job contract simple and avoids NameError.
        """
        if IntervalTrigger is None:
            return {"type": "interval", "minutes": minutes}
        return IntervalTrigger(minutes=minutes)

    @staticmethod
    def _build_cron_trigger(*, hour: int, minute: int):
        if CronTrigger is None:
            return {"type": "cron", "hour": hour, "minute": minute}
        return CronTrigger(hour=hour, minute=minute)

    @staticmethod
    def _parse_time(value: str) -> dict[str, int] | None:
        try:
            parsed = datetime.strptime(value, "%H:%M")
        except ValueError:
            return None
        return {"hour": parsed.hour, "minute": parsed.minute}

    async def _trigger_run_batch(self):
        logger.info("[EventEngine] batch trigger: %s", self.watchlists)
        if not self.watchlists:
            logger.warning("[EventEngine] watchlist is empty, skip")
            return
        results = await self.runner.run_batch(self.watchlists, execute_orders=self.execute_orders)
        logger.info("[EventEngine] batch completed: %d symbols", len(results))

    async def _trigger_day_roll(self):
        if not hasattr(self.runner, "day_roll"):
            return
        result = await self.runner.day_roll(reason="scheduled", force=False)
        if result.get("skipped"):
            logger.info("[EventEngine] day-roll skipped: %s", result.get("code", "NON_TRADING_DAY"))
            return
        logger.info(
            "[EventEngine] day-roll completed: %s",
            result.get("reconciliation", {}).get("status", "unknown"),
        )
