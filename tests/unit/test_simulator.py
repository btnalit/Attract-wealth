from __future__ import annotations

import asyncio

from src.execution.simulator import SimulatorBroker


def test_load_portfolio_snapshot_updates_balance_and_positions():
    broker = SimulatorBroker(initial_balance=1_000_000.0)
    broker.load_portfolio_snapshot(
        cash=968_888.0,
        positions={"000001": 500, "EMPTY": 0},
        reset_orders=True,
    )

    balance = asyncio.run(broker.get_balance())
    positions = asyncio.run(broker.get_positions())

    assert balance.available_cash == 968_888.0
    assert {item.ticker: item.quantity for item in positions} == {"000001": 500}
    assert positions[0].available == 500
