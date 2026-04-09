from __future__ import annotations

from pathlib import Path

from src.dataflows.cache import manager as cache_module


def _build_cache_manager():
    cache_module.CACHE_DB = Path(":memory:")
    manager = cache_module.CacheManager(memory_ttl=60)
    return manager


def test_cache_metrics_hit_and_backsource_rate():
    manager = _build_cache_manager()
    try:
        manager.set("k1", {"value": 1}, ttl=120)
        assert manager.get("k1") == {"value": 1}  # memory hit

        manager._memory_cache.clear()
        assert manager.get("k1") == {"value": 1}  # sqlite hit
        assert manager.get("missing-key") is None  # miss

        metrics = manager.get_metrics()
        assert metrics["requests"] == 3
        assert metrics["memory_hits"] == 1
        assert metrics["sqlite_hits"] == 1
        assert metrics["misses"] == 1
        assert metrics["hit_rate"] == round(2 / 3, 4)
        assert metrics["backsource_rate"] == round(1 / 3, 4)
    finally:
        manager.conn.close()
