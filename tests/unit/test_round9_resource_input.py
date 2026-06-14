"""第九轮回归测试：资源泄漏（N9-1）+ 输入校验（N9-2/3）。"""
from __future__ import annotations

import os

os.environ.setdefault("TRADING_CHANNEL", "simulation")

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.dataflows.cache.manager import CacheManager
from src.main import app
from src.routers.trading import DirectOrderRequest


# ---------------------------------------------------------------------------
# N9-1: CacheManager.close() 优雅关闭
# ---------------------------------------------------------------------------


class TestCacheManagerClose:
    def test_close_releases_connection(self, tmp_path):
        """close() 后连接应被关闭，再次 close 幂等。"""
        from src.dataflows.cache import manager as mgr_mod

        # 用独立实例避免污染全局单例
        cm = CacheManager.__new__(CacheManager)
        cm._memory_cache = {}
        cm.memory_ttl = 60
        import threading
        cm._lock = threading.RLock()
        cm._metrics = {k: 0 for k in [
            "requests", "memory_hits", "sqlite_hits", "misses", "writes",
            "memory_expired", "sqlite_expired", "sqlite_cleanups", "sqlite_cleanup_removed",
        ]}
        # 临时指向 tmp_path 的 db
        import pathlib
        orig_cache_db = mgr_mod.CACHE_DB
        mgr_mod.CACHE_DB = pathlib.Path(tmp_path) / "test_cache.db"
        try:
            cm._init_sqlite()
            assert cm.conn is not None
            cm.close()
            assert cm.conn is None  # type: ignore[comparison-overlap]
            # 幂等：再次 close 不抛
            cm.close()
        finally:
            mgr_mod.CACHE_DB = orig_cache_db


# ---------------------------------------------------------------------------
# N9-2: DirectOrderRequest ticker/side 校验
# ---------------------------------------------------------------------------


class TestDirectOrderRequestValidation:
    def _base_kwargs(self, **overrides):
        defaults = {
            "ticker": "000001",
            "side": "BUY",
            "price": 10.0,
            "idempotency_key": "test-key",
        }
        defaults.update(overrides)
        return defaults

    def test_valid_ticker_accepted(self):
        req = DirectOrderRequest(**self._base_kwargs(ticker="000001"))
        assert req.ticker == "000001"

    def test_valid_ticker_with_dot_accepted(self):
        req = DirectOrderRequest(**self._base_kwargs(ticker="SH.600000"))
        assert req.ticker == "SH.600000"

    def test_ticker_with_slash_rejected(self):
        with pytest.raises(ValidationError):
            DirectOrderRequest(**self._base_kwargs(ticker="../evil"))

    def test_ticker_with_space_rejected(self):
        with pytest.raises(ValidationError):
            DirectOrderRequest(**self._base_kwargs(ticker="000 001"))

    def test_ticker_empty_rejected(self):
        with pytest.raises(ValidationError):
            DirectOrderRequest(**self._base_kwargs(ticker=""))

    def test_ticker_special_chars_rejected(self):
        with pytest.raises(ValidationError):
            DirectOrderRequest(**self._base_kwargs(ticker="000001;rm -rf"))

    def test_invalid_side_rejected(self):
        with pytest.raises(ValidationError):
            DirectOrderRequest(**self._base_kwargs(side="HOLD"))

    def test_invalid_side_arbitrary_rejected(self):
        with pytest.raises(ValidationError):
            DirectOrderRequest(**self._base_kwargs(side="DELETE_ALL"))

    def test_lowercase_side_accepted(self):
        """小写 buy/sell 应被 Literal 接受（下游会 .upper()）。"""
        req = DirectOrderRequest(**self._base_kwargs(side="buy"))
        assert req.side == "buy"


# ---------------------------------------------------------------------------
# N9-2 端到端：非法 ticker/side 应返回 422
# ---------------------------------------------------------------------------


class TestDirectOrderEndpointValidation:
    @pytest.fixture()
    def client(self):
        with TestClient(app) as c:
            yield c

    def test_slash_ticker_returns_422(self, client):
        r = client.post("/api/trading/orders/direct", json={
            "ticker": "../evil", "side": "BUY", "quantity": 100,
            "price": 10.0, "idempotency_key": "e2e-1",
        })
        assert r.status_code == 422

    def test_invalid_side_returns_422(self, client):
        r = client.post("/api/trading/orders/direct", json={
            "ticker": "000001", "side": "HACK", "quantity": 100,
            "price": 10.0, "idempotency_key": "e2e-2",
        })
        assert r.status_code == 422

    def test_valid_order_still_works(self, client):
        r = client.post("/api/trading/orders/direct", json={
            "ticker": "000097", "side": "BUY", "quantity": 100,
            "price": 10.0, "idempotency_key": "e2e-valid-r9",
        })
        assert r.status_code == 200
        body = r.json()
        # 成功响应在 data 包络里
        data = body.get("data", body)
        assert data.get("risk_check", {}).get("passed") is True


# ---------------------------------------------------------------------------
# N9-3: bars max_length 校验
# ---------------------------------------------------------------------------


class TestBacktestBarsLimit:
    def test_too_many_bars_rejected(self):
        from src.routers.strategy import StrategyBacktestRequest

        bars = [{"close": 10.0} for _ in range(5001)]
        with pytest.raises(ValidationError):
            StrategyBacktestRequest(strategy_id="s1", bars=bars)

    def test_max_bars_accepted(self):
        from src.routers.strategy import StrategyBacktestRequest

        bars = [{"close": 10.0} for _ in range(5000)]
        req = StrategyBacktestRequest(strategy_id="s1", bars=bars)
        assert len(req.bars) == 5000
