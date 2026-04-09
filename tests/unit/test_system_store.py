from __future__ import annotations

import uuid

from src.core.system_store import SystemStore


def test_watchlist_persistence_roundtrip():
    store = SystemStore()
    name = f"unit-watchlist-{uuid.uuid4().hex[:8]}"
    saved = store.save_watchlist(["000001", "300059", "000001"], name=name, source="unit")
    loaded = store.load_watchlist(name=name)
    assert saved == ["000001", "300059"]
    assert loaded == ["000001", "300059"]


def test_settings_roundtrip():
    store = SystemStore()
    key = f"unit-setting-{uuid.uuid4().hex[:8]}"
    payload = {"enabled": True, "threshold": 2}
    store.set_setting(key, payload)
    loaded = store.get_setting(key, default={})
    assert loaded == payload
