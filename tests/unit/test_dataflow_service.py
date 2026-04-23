from __future__ import annotations

from src.services.dataflow_service import DataflowService


class _FakeManager:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def get_provider_instance(self, name=None):  # noqa: ANN001, ARG002
        return None

    def get_kline(self, ticker: str, start_date: str, end_date: str, timeframe: str = "D"):
        self.calls.append(
            {
                "ticker": ticker,
                "start_date": start_date,
                "end_date": end_date,
                "timeframe": timeframe,
            }
        )
        return []


def test_dataflow_service_maps_weekly_interval_to_w_timeframe():
    manager = _FakeManager()
    service = DataflowService(manager=manager)
    payload = service.get_market_kline("600000", limit=30, interval="weekly")
    assert payload == []
    assert manager.calls
    assert manager.calls[0]["timeframe"] == "W"


def test_dataflow_service_defaults_invalid_interval_to_daily():
    manager = _FakeManager()
    service = DataflowService(manager=manager)
    payload = service.get_market_kline("600000", limit=30, interval="unsupported_interval")
    assert payload == []
    assert manager.calls
    assert manager.calls[0]["timeframe"] == "D"
