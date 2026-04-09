"""
Autopilot templates for scheduler presets.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_AUTOPILOT_TEMPLATES: dict[str, dict[str, Any]] = {
    "balanced": {
        "name": "balanced",
        "description": "默认平衡模式：常规轮询 + 尾盘扫描 + 日切",
        "execute_orders": True,
        "schedule": {
            "interval_minutes": 15,
            "tail_attack_time": "14:45",
            "day_roll_time": "15:05",
        },
    },
    "conservative": {
        "name": "conservative",
        "description": "保守模式：只做分析，不自动下单",
        "execute_orders": False,
        "schedule": {
            "interval_minutes": 30,
            "tail_attack_time": "",
            "day_roll_time": "15:05",
        },
    },
    "aggressive": {
        "name": "aggressive",
        "description": "积极模式：高频轮询 + 尾盘扫描 + 日切",
        "execute_orders": True,
        "schedule": {
            "interval_minutes": 5,
            "tail_attack_time": "14:40",
            "day_roll_time": "15:05",
        },
    },
}


def load_autopilot_templates(config_path: str | None = None) -> dict[str, dict[str, Any]]:
    root = Path(__file__).resolve().parent.parent.parent
    path = Path(config_path) if config_path else root / "config" / "autopilot_templates.json"
    templates = {name: _normalize_template(name, payload) for name, payload in DEFAULT_AUTOPILOT_TEMPLATES.items()}

    if not path.exists():
        return templates

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return templates

    source = payload.get("templates", payload) if isinstance(payload, dict) else {}
    if not isinstance(source, dict):
        return templates

    for name, raw_template in source.items():
        normalized = _normalize_template(str(name), raw_template)
        if normalized:
            templates[normalized["name"]] = normalized
    return templates


def _normalize_template(name: str, raw_template: Any) -> dict[str, Any]:
    if not isinstance(raw_template, dict):
        return {}
    schedule_raw = raw_template.get("schedule", {})
    schedule = schedule_raw if isinstance(schedule_raw, dict) else {}
    try:
        interval = int(schedule.get("interval_minutes", 0) or 0)
    except ValueError:
        interval = 0
    interval = max(0, interval)

    normalized_name = str(raw_template.get("name", name)).strip().lower()
    return {
        "name": normalized_name,
        "description": str(raw_template.get("description", "")).strip(),
        "execute_orders": bool(raw_template.get("execute_orders", True)),
        "schedule": {
            "interval_minutes": interval,
            "tail_attack_time": str(schedule.get("tail_attack_time", "")).strip(),
            "day_roll_time": str(schedule.get("day_roll_time", "")).strip(),
        },
    }
