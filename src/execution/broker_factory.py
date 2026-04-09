"""Broker factory."""
from __future__ import annotations

import os
from typing import Optional

from src.execution.base import AccountBalance, BaseBroker, OrderResult, Position
from src.execution.qmt_broker import QMTBroker
from src.execution.simulator import SimulatorBroker
from src.execution.ths_broker import THSBroker
from src.execution.ths_ipc.broker import THSIPCBroker
from src.core.ths_path_resolver import resolve_ths_path


class THSDisconnectedBroker(BaseBroker):
    """Placeholder broker when THS xiadan.exe is not found.
    Ensures the system does not silently downgrade to simulation.
    """

    channel_name = "ths_auto"

    def __init__(self, path: str, source: str):
        self.path = path
        self.source = source

    @property
    def is_connected(self) -> bool:
        return False

    async def connect(self) -> bool:
        return False

    async def disconnect(self):
        pass

    async def buy(self, ticker: str, price: float, quantity: int, **kwargs) -> OrderResult:
        return OrderResult(ticker=ticker, status="failed", message=f"THS_NOT_FOUND at {self.path}")

    async def sell(self, ticker: str, price: float, quantity: int, **kwargs) -> OrderResult:
        return OrderResult(ticker=ticker, status="failed", message=f"THS_NOT_FOUND at {self.path}")

    async def cancel(self, order_id: str) -> bool:
        return False

    async def get_positions(self) -> list[Position]:
        return []

    async def get_balance(self) -> AccountBalance:
        return AccountBalance()

    async def get_orders(self, date: str | None = None) -> list[OrderResult]:
        return []

    def get_status(self) -> dict:
        return {"error": "THS_NOT_FOUND", "path": self.path, "source": self.source}

    def check_health(self) -> dict:
        return {
            "hwnd": None,
            "title": "",
            "status": "dead",
            "error": "THS_NOT_FOUND",
            "path": self.path,
            "is_connected": False,
        }


def create_broker(channel: Optional[str] = None) -> BaseBroker:
    """Create execution broker by channel."""
    selected = (channel or os.getenv("TRADING_CHANNEL", "ths_auto")).strip().lower()

    if selected == "simulation":
        initial_balance = float(os.getenv("SIM_INITIAL_BALANCE", "1000000"))
        return SimulatorBroker(initial_balance=initial_balance)

    if selected == "ths_ipc":
        host = os.getenv("THS_IPC_HOST", "127.0.0.1")
        port = int(os.getenv("THS_IPC_PORT", "8089"))
        return THSIPCBroker(host=host, port=port)

    if selected == "ths_auto":
        # Phase 6: 自适应 THS 路径探测
        ths_info = resolve_ths_path()
        if ths_info.get("found") and ths_info.get("exe_path"):
            exe_path = ths_info["exe_path"]
        else:
            exe_path = os.getenv("THS_EXE_PATH", "")
        if exe_path and os.path.isfile(exe_path):
            return THSBroker(exe_path=exe_path)
        # Avoid silent downgrade to simulation.
        import logging
        logging.getLogger(__name__).error(
            "THS 路径未找到 (source=%s: %s)，返回断开状态 Broker", ths_info.get("source", "unknown"), exe_path
        )
        return THSDisconnectedBroker(path=exe_path, source=ths_info.get("source", "unknown"))

    if selected == "qmt":
        account_id = os.getenv("QMT_ACCOUNT_ID", "").strip() or os.getenv("QMT_ACCOUNT", "").strip()
        if not account_id:
            raise ValueError("QMT_ACCOUNT_ID/QMT_ACCOUNT 未配置，无法创建 qmt 通道。")
        mini_qmt_path = os.getenv("QMT_PATH", r"D:\国金证券QMT交易端\userdata_mini")
        return QMTBroker(account_id=account_id, mini_qmt_path=mini_qmt_path)

    raise ValueError(f"不支持的交易通道: {selected}")

