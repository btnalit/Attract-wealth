from __future__ import annotations

from dataclasses import dataclass

from src.core.event_engine import EventEngine
from src.core.system_store import SystemStore


@dataclass
class _Job:
    id: str
    next_run_time: object = None


class _FakeScheduler:
    def __init__(self):
        self.jobs: dict[str, _Job] = {}

    def add_job(self, _fn, _trigger, id: str, replace_existing: bool = False, name: str | None = None):
        if not replace_existing and id in self.jobs:
            raise ValueError("job exists")
        self.jobs[id] = _Job(id=id)
        return self.jobs[id]

    def remove_job(self, job_id: str):
        if job_id not in self.jobs:
            raise KeyError(job_id)
        self.jobs.pop(job_id, None)

    def get_jobs(self):
        return list(self.jobs.values())

    def start(self):
        return None

    def shutdown(self):
        return None


class _Runner:
    async def run_batch(self, *_args, **_kwargs):
        return []

    async def day_roll(self, *_args, **_kwargs):
        return {"skipped": True}


def test_apply_autopilot_template_updates_jobs_and_mode():
    templates = {
        "unit": {
            "name": "unit",
            "description": "unit",
            "execute_orders": False,
            "schedule": {"interval_minutes": 10, "tail_attack_time": "14:45", "day_roll_time": "15:05"},
        }
    }
    engine = EventEngine(runner=_Runner(), execute_orders=True, autopilot_templates=templates)
    engine.scheduler = _FakeScheduler()

    state = engine.apply_autopilot_template("unit", persist=False)
    assert engine.execute_orders is False
    assert state["active_template"] == "unit"
    assert {job.id for job in engine.scheduler.get_jobs()} == {"interval_polling", "tail_attack", "day_roll"}


def test_restore_watchlist_prefers_storage():
    store = SystemStore()
    store.save_watchlist(["600519", "000001"], source="unit")

    engine = EventEngine(runner=_Runner(), system_store=store)
    restored = engine.restore_watchlists(["300059"])
    assert restored == ["600519", "000001"]


def test_restore_watchlist_keeps_persisted_empty_list():
    store = SystemStore()
    store.save_watchlist([], source="unit")

    engine = EventEngine(runner=_Runner(), system_store=store)
    restored = engine.restore_watchlists(["300059"])
    assert restored == []
