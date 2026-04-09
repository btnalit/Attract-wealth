from __future__ import annotations

from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

import src.dataflows.source_manager as source_manager_module
from src.dataflows.cache import manager as cache_module
from src.dataflows.source_manager import BaseDataSource, DataSourceManager


class _FailingProvider(BaseDataSource):
    def get_kline(self, ticker: str, start_date: str, end_date: str, timeframe: str = "D") -> pd.DataFrame:
        raise RuntimeError("primary down")

    def get_fundamentals(self, ticker: str) -> dict:
        raise RuntimeError("primary down")

    def get_news(self, ticker: str, limit: int = 10) -> list[dict]:
        raise RuntimeError("primary down")


class _GoodProvider(BaseDataSource):
    def __init__(self):
        self.news_calls = 0

    def get_kline(self, ticker: str, start_date: str, end_date: str, timeframe: str = "D") -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"date": "2026-04-07", "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.1, "volume": 10000},
                {"date": "2026-04-08", "open": 10.1, "high": 10.8, "low": 10.0, "close": 10.6, "volume": 12000},
            ]
        )

    def get_fundamentals(self, ticker: str) -> dict:
        return {"ticker": ticker, "pe_ttm": 12.3}

    def get_news(self, ticker: str, limit: int = 10) -> list[dict]:
        self.news_calls += 1
        return [{"title": f"{ticker} news", "content": "ok"}]


class _StaleProvider(BaseDataSource):
    def get_kline(self, ticker: str, start_date: str, end_date: str, timeframe: str = "D") -> pd.DataFrame:
        return pd.DataFrame(
            [{"date": "2025-01-01", "open": 9.0, "high": 9.2, "low": 8.8, "close": 9.1, "volume": 8000}]
        )

    def get_fundamentals(self, ticker: str) -> dict:
        return {}

    def get_news(self, ticker: str, limit: int = 10) -> list[dict]:
        return []


class _NewsOnlyFailingProvider(BaseDataSource):
    def get_kline(self, ticker: str, start_date: str, end_date: str, timeframe: str = "D") -> pd.DataFrame:
        return pd.DataFrame()

    def get_fundamentals(self, ticker: str) -> dict:
        return {}

    def get_news(self, ticker: str, limit: int = 10) -> list[dict]:
        raise RuntimeError("news source failed")


class _FlakyNewsProvider(BaseDataSource):
    def __init__(self, fail_times: int = 1):
        self._fail_times = max(0, int(fail_times))
        self.calls = 0

    def get_kline(self, ticker: str, start_date: str, end_date: str, timeframe: str = "D") -> pd.DataFrame:
        return pd.DataFrame()

    def get_fundamentals(self, ticker: str) -> dict:
        return {}

    def get_news(self, ticker: str, limit: int = 10) -> list[dict]:
        self.calls += 1
        if self.calls <= self._fail_times:
            raise RuntimeError("transient news error")
        return [{"title": f"{ticker} retry ok", "limit": limit}]


def _build_cache_manager(tmp_path: Path):
    _ = tmp_path
    cache_module.CACHE_DB = Path(":memory:")
    return cache_module.CacheManager(memory_ttl=60)


def test_data_source_manager_fallback_on_provider_error():
    manager = DataSourceManager(cache=None)
    manager.register("primary", _FailingProvider(), priority=10, is_primary=True)
    manager.register("backup", _GoodProvider(), priority=20)

    df = manager.get_kline("000001", "2026-04-01", "2026-04-08")
    assert not df.empty

    metrics = manager.get_metrics()
    assert metrics["fallback_total"] == 1
    assert metrics["methods"]["get_kline"]["fallback"] == 1
    assert metrics["providers"]["primary"]["failure"] >= 1
    assert metrics["providers"]["backup"]["success"] >= 1


def test_data_source_manager_cache_hit_reduces_backsource():
    cache = _build_cache_manager(Path("."))
    provider = _GoodProvider()
    manager = DataSourceManager(cache=cache)
    manager.register("primary", provider, priority=10, is_primary=True)

    try:
        first = manager.get_news("000001", limit=1)
        second = manager.get_news("000001", limit=1)

        assert first == second
        assert provider.news_calls == 1

        metrics = manager.get_metrics()
        assert metrics["local_cache"]["requests"] == 2
        assert metrics["local_cache"]["hits"] == 1
        assert metrics["local_cache"]["misses"] == 1
    finally:
        cache.conn.close()


def test_data_source_manager_tracks_stale_kline():
    manager = DataSourceManager(cache=None, stale_kline_days=3)
    manager.register("stale", _StaleProvider(), priority=10, is_primary=True)

    df = manager.get_kline("000001", "2025-01-01", "2025-01-10")
    assert not df.empty

    metrics = manager.get_metrics()
    assert metrics["stale_kline_total"] == 1
    assert metrics["kline_last_age_days"] is not None
    assert metrics["kline_last_age_days"] > 3


def test_data_source_manager_quality_warn_from_provider_health(monkeypatch):
    monkeypatch.setenv("DATA_QUALITY_PROVIDER_MIN_REQUESTS", "1")
    monkeypatch.setenv("DATA_QUALITY_PROVIDER_ERROR_WARN", "0.2")
    monkeypatch.setenv("DATA_QUALITY_PROVIDER_ERROR_BLOCK", "2.0")

    manager = DataSourceManager(cache=None)
    manager.register("primary", _NewsOnlyFailingProvider(), priority=10, is_primary=True)
    manager.register("backup", _GoodProvider(), priority=20)

    news = manager.get_news("000001", limit=1)
    assert len(news) == 1

    metrics = manager.get_metrics()
    quality = metrics["quality"]
    assert quality["alert_level"] == "warn"
    assert quality["code"] == "DATA_QUALITY_WARN"
    assert quality["action"] == "record"
    assert any(rule["rule"].startswith("provider_health:primary") for rule in quality["triggered_rules"])


def test_data_source_manager_quality_block_from_error_rate(monkeypatch):
    monkeypatch.setenv("DATA_QUALITY_ERROR_WARN", "0.2")
    monkeypatch.setenv("DATA_QUALITY_ERROR_BLOCK", "0.5")
    monkeypatch.setenv("DATA_QUALITY_PROVIDER_MIN_REQUESTS", "1")
    monkeypatch.setenv("DATA_QUALITY_PROVIDER_ERROR_WARN", "2.0")
    monkeypatch.setenv("DATA_QUALITY_PROVIDER_ERROR_BLOCK", "3.0")

    manager = DataSourceManager(cache=None)
    manager.register("primary", _NewsOnlyFailingProvider(), priority=10, is_primary=True)

    news = manager.get_news("000001", limit=1)
    assert news == []

    metrics = manager.get_metrics()
    quality = metrics["quality"]
    assert metrics["error_rate"] == 1.0
    assert quality["alert_level"] == "critical"
    assert quality["code"] == "DATA_QUALITY_BLOCK"
    assert quality["action"] == "block"


def test_data_source_manager_retry_success_metrics(monkeypatch):
    monkeypatch.setenv("DATA_PROVIDER_BACKOFF_RETRIES", "2")
    monkeypatch.setenv("DATA_PROVIDER_BACKOFF_BASE_MS", "0")
    monkeypatch.setenv("DATA_PROVIDER_BACKOFF_MAX_MS", "1")

    manager = DataSourceManager(cache=None)
    flaky = _FlakyNewsProvider(fail_times=1)
    manager.register("primary", flaky, priority=10, is_primary=True)

    news = manager.get_news("000001", limit=1)
    assert len(news) == 1

    metrics = manager.get_metrics()
    assert metrics["retries_total"] == 1
    assert metrics["retry_success_total"] == 1
    assert metrics["providers"]["primary"]["retries"] == 1
    assert metrics["providers"]["primary"]["retry_success"] == 1
    assert metrics["summary"]["retry_rate"] > 0
    assert metrics["summary"]["tuning_action"] in {"tune", "urgent_tune"}
    assert "DATA_PROVIDER_BACKOFF_RETRIES" in metrics["tuning"]["suggested_env"]


def test_data_source_manager_rate_limit_fallback_and_quality(monkeypatch):
    monkeypatch.setenv("DATA_PROVIDER_RATE_LIMIT_PER_MINUTE", "1")
    monkeypatch.setenv("DATA_PROVIDER_MIN_INTERVAL_MS", "0")
    monkeypatch.setenv("DATA_PROVIDER_MAX_WAIT_MS", "0")
    monkeypatch.setenv("DATA_QUALITY_RATE_LIMIT_WARN", "0.1")
    monkeypatch.setenv("DATA_QUALITY_RATE_LIMIT_BLOCK", "0.2")
    monkeypatch.setenv("DATA_QUALITY_PROVIDER_MIN_REQUESTS", "99")

    primary = _GoodProvider()
    backup = _GoodProvider()
    manager = DataSourceManager(cache=None)
    manager.register("primary", primary, priority=10, is_primary=True)
    manager.register("backup", backup, priority=20)

    assert manager.get_news("000001", limit=1)
    assert manager.get_news("000001", limit=2)

    metrics = manager.get_metrics()
    assert metrics["rate_limited_total"] >= 1
    assert metrics["providers"]["primary"]["rate_limited"] >= 1
    assert metrics["fallback_total"] >= 1
    assert backup.news_calls >= 1

    quality = metrics["quality"]
    assert quality["alert_level"] == "critical"
    assert quality["code"] == "DATA_QUALITY_BLOCK"
    assert any(rule["rule"] == "overall_rate_limited_rate" for rule in quality["triggered_rules"])
    assert metrics["summary"]["tuning_action"] == "urgent_tune"
    assert "DATA_PROVIDER_MAX_WAIT_MS" in metrics["tuning"]["suggested_env"]


def test_data_source_manager_reload_runtime_config_from_env(monkeypatch):
    manager = DataSourceManager(cache=None)
    monkeypatch.setenv("DATA_PROVIDER_RATE_LIMIT_PER_MINUTE", "66")
    monkeypatch.setenv("DATA_PROVIDER_BACKOFF_RETRIES", "5")
    monkeypatch.setenv("DATA_QUALITY_ERROR_BLOCK", "0.22")

    runtime = manager.reload_runtime_config_from_env()
    assert runtime["provider_rate_limit"]["per_minute"] == 66
    assert runtime["retry_policy"]["max_retries"] == 5
    assert runtime["quality_thresholds"]["error_block"] == 0.22

    metrics = manager.get_metrics()
    assert metrics["runtime_config"]["provider_rate_limit"]["per_minute"] == 66


def test_bootstrap_default_sources_can_be_disabled(monkeypatch):
    monkeypatch.setenv("DATA_SOURCE_BOOTSTRAP_AKSHARE", "false")
    manager = DataSourceManager(cache=None)
    source_manager_module._bootstrap_default_sources(manager)
    assert "akshare" not in manager._providers


def test_data_source_manager_quality_feedback_metrics_and_events(monkeypatch):
    monkeypatch.setenv("DATA_QUALITY_RATE_LIMIT_WARN", "0.1")
    monkeypatch.setenv("DATA_QUALITY_RATE_LIMIT_BLOCK", "0.2")
    monkeypatch.setenv("DATA_QUALITY_PROVIDER_MIN_REQUESTS", "99")
    monkeypatch.setenv("DATA_PROVIDER_RATE_LIMIT_PER_MINUTE", "1")
    monkeypatch.setenv("DATA_PROVIDER_MIN_INTERVAL_MS", "0")
    monkeypatch.setenv("DATA_PROVIDER_MAX_WAIT_MS", "0")

    manager = DataSourceManager(cache=None)
    manager.register("primary", _GoodProvider(), priority=10, is_primary=True)
    manager.register("backup", _GoodProvider(), priority=20)

    # Trigger one critical quality event.
    manager.get_news("000001", limit=1)
    manager.get_news("000001", limit=2)
    metrics = manager.get_metrics()

    assert metrics["quality"]["event_id"]
    assert metrics["quality_feedback"]["feedback_total"] == 0
    assert isinstance(metrics["quality_events"], list)

    feedback = manager.record_quality_feedback(
        label="true_positive",
        event_id=metrics["quality"]["event_id"],
        source="unit-test",
        note="alert was valid",
    )
    assert feedback["feedback_total"] == 1
    assert feedback["precision"] == 1.0

    manager.record_quality_feedback(label="false_positive", event_id=metrics["quality"]["event_id"])
    manager.record_quality_feedback(label="false_negative", event_id=metrics["quality"]["event_id"])
    feedback2 = manager.get_quality_feedback_metrics()
    assert feedback2["feedback_total"] == 3
    assert feedback2["false_positive_rate"] == 0.5
    assert feedback2["miss_rate"] == 0.5
