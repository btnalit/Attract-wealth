"""Memory vault DAO: persistence boundary for memory tier overrides and forgotten set."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from src.core.storage import DATA_DIR

_ALLOWED_TIERS = {"HOT", "WARM", "COLD"}


class MemoryVaultDAO:
    """DAO for memory vault user actions persisted on local disk."""

    def __init__(self, file_path: str | Path | None = None) -> None:
        self._file_path = Path(file_path) if file_path else DATA_DIR / "memory_vault_overrides.json"
        self._lock = threading.Lock()

    @staticmethod
    def _normalize_tier(value: Any) -> str | None:
        tier = str(value or "").strip().upper()
        if tier in _ALLOWED_TIERS:
            return tier
        return None

    @staticmethod
    def _normalize_state(raw: Any) -> dict[str, Any]:
        payload = raw if isinstance(raw, dict) else {}

        tiers: dict[str, str] = {}
        raw_tiers = payload.get("tiers", {})
        if isinstance(raw_tiers, dict):
            for entry_id, tier in raw_tiers.items():
                normalized_tier = MemoryVaultDAO._normalize_tier(tier)
                normalized_id = str(entry_id or "").strip()
                if normalized_id and normalized_tier:
                    tiers[normalized_id] = normalized_tier

        forgotten_set: set[str] = set()
        raw_forgotten = payload.get("forgotten", [])
        if isinstance(raw_forgotten, list):
            for entry_id in raw_forgotten:
                normalized_id = str(entry_id or "").strip()
                if normalized_id:
                    forgotten_set.add(normalized_id)

        return {
            "version": 1,
            "tiers": tiers,
            "forgotten": sorted(forgotten_set),
            "updated_at": float(payload.get("updated_at") or 0.0),
        }

    def _read_state(self) -> dict[str, Any]:
        if not self._file_path.exists():
            return {"version": 1, "tiers": {}, "forgotten": [], "updated_at": 0.0}
        try:
            raw = json.loads(self._file_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            raw = {}
        return self._normalize_state(raw)

    def _write_state(self, state: dict[str, Any]) -> None:
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        payload = self._normalize_state(state)
        payload["updated_at"] = time.time()
        self._file_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_overrides(self) -> dict[str, Any]:
        """Read current memory override state."""
        with self._lock:
            state = self._read_state()
        return {
            "tiers": dict(state.get("tiers", {})),
            "forgotten": list(state.get("forgotten", [])),
            "updated_at": float(state.get("updated_at", 0.0)),
        }

    def set_tier(self, *, entry_id: str, tier: str) -> dict[str, Any]:
        """Persist one entry tier override."""
        normalized_id = str(entry_id or "").strip()
        normalized_tier = self._normalize_tier(tier)
        if not normalized_id:
            raise ValueError("entry_id 不能为空")
        if not normalized_tier:
            raise ValueError("tier 必须为 HOT/WARM/COLD")

        with self._lock:
            state = self._read_state()
            tiers = dict(state.get("tiers", {}))
            tiers[normalized_id] = normalized_tier
            forgotten = [item for item in state.get("forgotten", []) if item != normalized_id]
            state["tiers"] = tiers
            state["forgotten"] = forgotten
            self._write_state(state)

        return {"id": normalized_id, "tier": normalized_tier}

    def forget(self, *, entry_id: str) -> dict[str, Any]:
        """Persist one entry as forgotten."""
        normalized_id = str(entry_id or "").strip()
        if not normalized_id:
            raise ValueError("entry_id 不能为空")

        with self._lock:
            state = self._read_state()
            tiers = dict(state.get("tiers", {}))
            tiers.pop(normalized_id, None)
            forgotten_set = set(state.get("forgotten", []))
            forgotten_set.add(normalized_id)
            state["tiers"] = tiers
            state["forgotten"] = sorted(forgotten_set)
            self._write_state(state)

        return {"id": normalized_id, "forgotten": True}
