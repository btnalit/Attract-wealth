from __future__ import annotations

import pytest

from src.execution import broker_factory


def test_create_qmt_broker_supports_legacy_account_env(monkeypatch):
    monkeypatch.delenv("QMT_ACCOUNT_ID", raising=False)
    monkeypatch.setenv("QMT_ACCOUNT", "legacy-account")
    monkeypatch.setenv("QMT_PATH", r"D:\qmt")

    class _DummyBroker:
        def __init__(self, account_id: str, mini_qmt_path: str):
            self.account_id = account_id
            self.mini_qmt_path = mini_qmt_path

    monkeypatch.setattr(broker_factory, "QMTBroker", _DummyBroker)
    broker = broker_factory.create_broker("qmt")
    assert broker.account_id == "legacy-account"
    assert broker.mini_qmt_path == r"D:\qmt"


def test_create_qmt_broker_requires_account(monkeypatch):
    monkeypatch.delenv("QMT_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("QMT_ACCOUNT", raising=False)
    with pytest.raises(ValueError):
        broker_factory.create_broker("qmt")
