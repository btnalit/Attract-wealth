from src.execution.base import OrderStatus
from src.execution.qmt_broker import _map_qmt_status
from src.execution.ths_ipc.broker import _map_ths_status


def test_qmt_status_mapping_by_traded_volume():
    assert _map_qmt_status(status_code=0, traded_volume=100, order_volume=100) == OrderStatus.FILLED
    assert _map_qmt_status(status_code=0, traded_volume=50, order_volume=100) == OrderStatus.PARTIAL


def test_qmt_status_mapping_by_status_code():
    assert _map_qmt_status(status_code=56, traded_volume=0, order_volume=100) == OrderStatus.CANCELLED
    assert _map_qmt_status(status_code=49, traded_volume=0, order_volume=100) == OrderStatus.REJECTED
    assert _map_qmt_status(status_code=2, traded_volume=0, order_volume=100) == OrderStatus.SUBMITTED


def test_ths_status_mapping():
    assert _map_ths_status("submitted") == OrderStatus.SUBMITTED
    assert _map_ths_status("filled") == OrderStatus.FILLED
    assert _map_ths_status("cancelled") == OrderStatus.CANCELLED
