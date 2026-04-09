"""Broker factory."""
from __future__ import annotations

import os
from typing import Optional

from src.execution.base import BaseBroker
from src.execution.qmt_broker import QMTBroker
from src.execution.simulator import SimulatorBroker
from src.execution.ths_broker import THSBroker
from src.execution.ths_ipc.broker import THSIPCBroker


def create_broker(channel: Optional[str] = None) -> BaseBroker:
    """Create execution broker by channel."""
    selected = (channel or os.getenv("TRADING_CHANNEL", "simulation")).strip().lower()

    if selected == "simulation":
        initial_balance = float(os.getenv("SIM_INITIAL_BALANCE", "1000000"))
        return SimulatorBroker(initial_balance=initial_balance)

    if selected == "ths_ipc":
        host = os.getenv("THS_IPC_HOST", "127.0.0.1")
        port = int(os.getenv("THS_IPC_PORT", "8089"))
        return THSIPCBroker(host=host, port=port)

    if selected == "ths_auto":
        exe_path = os.getenv("THS_EXE_PATH", r"D:\同花顺软件\同花顺\xiadan.exe")
        return THSBroker(exe_path=exe_path)

    if selected == "qmt":
        account_id = os.getenv("QMT_ACCOUNT_ID", "").strip() or os.getenv("QMT_ACCOUNT", "").strip()
        if not account_id:
            raise ValueError("QMT_ACCOUNT_ID/QMT_ACCOUNT 未配置，无法创建 qmt 通道。")
        mini_qmt_path = os.getenv("QMT_PATH", r"D:\国金证券QMT交易端\userdata_mini")
        return QMTBroker(account_id=account_id, mini_qmt_path=mini_qmt_path)

    raise ValueError(f"不支持的交易通道: {selected}")

