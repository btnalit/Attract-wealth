from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass
class BacktestParams:
    start_cash: float = 1_000_000.0
    lot_size: int = 100
    commission_rate: float = 0.0003
    slippage_bp: float = 1.0
    position_ratio: float = 0.5
    lookback: int = 3
    buy_threshold: float = 0.01
    sell_threshold: float = -0.01


class BacktestRunner:
    """Simple single-asset backtest runner for strategy lifecycle gate."""

    def run(
        self,
        *,
        strategy_id: str,
        strategy_name: str,
        strategy_version: int,
        bars: list[dict[str, Any]],
        parameters: dict[str, Any] | None = None,
        start_cash: float = 1_000_000.0,
        lot_size: int = 100,
        commission_rate: float = 0.0003,
        slippage_bp: float = 1.0,
    ) -> dict[str, Any]:
        parsed_bars = self._normalize_bars(bars)
        if len(parsed_bars) < 2:
            raise ValueError("at least 2 bars are required for backtest")

        params = self._build_params(
            parameters=parameters or {},
            start_cash=start_cash,
            lot_size=lot_size,
            commission_rate=commission_rate,
            slippage_bp=slippage_bp,
        )

        cash = params.start_cash
        position = 0
        avg_cost = 0.0
        realized_pnl = 0.0
        trade_count = 0
        winning_trades = 0
        trades: list[dict[str, Any]] = []
        equity_curve: list[dict[str, Any]] = []
        signal_counts = {"BUY": 0, "SELL": 0, "HOLD": 0}

        for index, bar in enumerate(parsed_bars):
            close_price = bar["close"]
            signal = self._resolve_signal(parsed_bars, index, params, bar.get("signal", "AUTO"))
            signal_counts[signal] = signal_counts.get(signal, 0) + 1

            if signal == "BUY":
                target_value = (cash + position * close_price) * params.position_ratio
                execute_price = close_price * (1.0 + params.slippage_bp / 10_000.0)
                max_affordable = int(cash // (execute_price * (1.0 + params.commission_rate)))
                quantity = min(
                    self._normalize_lot_quantity(target_value / max(execute_price, 1e-8), params.lot_size),
                    self._normalize_lot_quantity(max_affordable, params.lot_size),
                )
                if quantity > 0:
                    trade_value = execute_price * quantity
                    fee = trade_value * params.commission_rate
                    cash -= trade_value + fee
                    new_position = position + quantity
                    if new_position > 0:
                        avg_cost = ((avg_cost * position) + trade_value + fee) / new_position
                    position = new_position
                    trade_count += 1
                    trades.append(
                        {
                            "step": index,
                            "signal": signal,
                            "price": round(execute_price, 6),
                            "quantity": int(quantity),
                            "fee": round(fee, 6),
                            "cash_after": round(cash, 6),
                            "position_after": int(position),
                        }
                    )

            elif signal == "SELL" and position > 0:
                quantity = self._normalize_lot_quantity(position, params.lot_size)
                if quantity <= 0:
                    quantity = position
                execute_price = close_price * (1.0 - params.slippage_bp / 10_000.0)
                trade_value = execute_price * quantity
                fee = trade_value * params.commission_rate
                cash += trade_value - fee
                pnl = (execute_price - avg_cost) * quantity - fee
                realized_pnl += pnl
                if pnl > 0:
                    winning_trades += 1
                position -= quantity
                if position <= 0:
                    position = 0
                    avg_cost = 0.0
                trade_count += 1
                trades.append(
                    {
                        "step": index,
                        "signal": signal,
                        "price": round(execute_price, 6),
                        "quantity": int(quantity),
                        "fee": round(fee, 6),
                        "pnl": round(pnl, 6),
                        "cash_after": round(cash, 6),
                        "position_after": int(position),
                    }
                )

            equity = cash + position * close_price
            equity_curve.append(
                {
                    "step": index,
                    "timestamp": bar.get("timestamp", ""),
                    "close": round(close_price, 6),
                    "signal": signal,
                    "equity": round(equity, 6),
                    "cash": round(cash, 6),
                    "position": int(position),
                }
            )

        final_close = parsed_bars[-1]["close"]
        final_equity = cash + position * final_close
        net_pnl = final_equity - params.start_cash
        total_return = net_pnl / params.start_cash if params.start_cash > 0 else 0.0
        win_rate = winning_trades / trade_count if trade_count > 0 else 0.0
        max_drawdown = self._max_drawdown([row["equity"] for row in equity_curve])
        sharpe = self._sharpe([row["equity"] for row in equity_curve])
        turnover = self._turnover(trades=trades, start_cash=params.start_cash)

        metrics = {
            "trade_count": int(trade_count),
            "winning_trades": int(winning_trades),
            "win_rate": round(win_rate, 6),
            "realized_pnl": round(realized_pnl, 6),
            "net_pnl": round(net_pnl, 6),
            "total_return": round(total_return, 6),
            "max_drawdown": round(max_drawdown, 6),
            "sharpe": round(sharpe, 6),
            "turnover": round(turnover, 6),
            "signal_counts": signal_counts,
        }

        return {
            "strategy": {
                "id": str(strategy_id),
                "name": str(strategy_name),
                "version": int(strategy_version),
            },
            "params": {
                "start_cash": params.start_cash,
                "lot_size": params.lot_size,
                "commission_rate": params.commission_rate,
                "slippage_bp": params.slippage_bp,
                "position_ratio": params.position_ratio,
                "lookback": params.lookback,
                "buy_threshold": params.buy_threshold,
                "sell_threshold": params.sell_threshold,
            },
            "metrics": metrics,
            "summary": {
                "bars": len(parsed_bars),
                "start_cash": round(params.start_cash, 6),
                "final_equity": round(final_equity, 6),
                "final_cash": round(cash, 6),
                "final_position": int(position),
                "final_close": round(final_close, 6),
            },
            "trades": trades,
            "equity_curve_tail": equity_curve[-50:],
        }

    @staticmethod
    def _normalize_bars(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
        parsed: list[dict[str, Any]] = []
        for index, row in enumerate(bars or []):
            close = _to_float((row or {}).get("close", 0.0), 0.0)
            if close <= 0:
                raise ValueError(f"bar[{index}].close must be > 0")
            parsed.append(
                {
                    "timestamp": str((row or {}).get("timestamp", "") or (row or {}).get("ts", "")),
                    "close": close,
                    "signal": str((row or {}).get("signal", "AUTO")).strip().upper(),
                }
            )
        return parsed

    @staticmethod
    def _normalize_lot_quantity(quantity: float, lot_size: int) -> int:
        if lot_size <= 1:
            return max(0, int(quantity))
        q = max(0, int(quantity))
        return (q // lot_size) * lot_size

    @staticmethod
    def _build_params(
        *,
        parameters: dict[str, Any],
        start_cash: float,
        lot_size: int,
        commission_rate: float,
        slippage_bp: float,
    ) -> BacktestParams:
        position_ratio = _to_float(parameters.get("position_ratio", 0.5), 0.5)
        lookback = _to_int(parameters.get("lookback", 3), 3)
        buy_threshold = _to_float(parameters.get("buy_threshold", 0.01), 0.01)
        sell_threshold = _to_float(parameters.get("sell_threshold", -0.01), -0.01)
        return BacktestParams(
            start_cash=max(1.0, _to_float(parameters.get("start_cash", start_cash), start_cash)),
            lot_size=max(1, _to_int(parameters.get("lot_size", lot_size), lot_size)),
            commission_rate=max(0.0, _to_float(parameters.get("commission_rate", commission_rate), commission_rate)),
            slippage_bp=max(0.0, _to_float(parameters.get("slippage_bp", slippage_bp), slippage_bp)),
            position_ratio=max(0.0, min(1.0, position_ratio)),
            lookback=max(1, lookback),
            buy_threshold=buy_threshold,
            sell_threshold=sell_threshold,
        )

    @staticmethod
    def _resolve_signal(
        bars: list[dict[str, Any]],
        index: int,
        params: BacktestParams,
        raw_signal: str,
    ) -> str:
        signal = str(raw_signal or "AUTO").strip().upper()
        if signal in {"BUY", "SELL", "HOLD"}:
            return signal
        if index < params.lookback:
            return "HOLD"
        current = bars[index]["close"]
        prev = bars[index - params.lookback]["close"]
        if prev <= 0:
            return "HOLD"
        momentum = current / prev - 1.0
        if momentum >= params.buy_threshold:
            return "BUY"
        if momentum <= params.sell_threshold:
            return "SELL"
        return "HOLD"

    @staticmethod
    def _max_drawdown(equity: list[float]) -> float:
        peak = -1.0
        max_dd = 0.0
        for value in equity:
            cur = _to_float(value, 0.0)
            if cur > peak:
                peak = cur
            if peak <= 0:
                continue
            drawdown = (peak - cur) / peak
            if drawdown > max_dd:
                max_dd = drawdown
        return max(0.0, max_dd)

    @staticmethod
    def _sharpe(equity: list[float]) -> float:
        if len(equity) < 3:
            return 0.0
        returns: list[float] = []
        for idx in range(1, len(equity)):
            prev = _to_float(equity[idx - 1], 0.0)
            cur = _to_float(equity[idx], 0.0)
            if prev <= 0:
                continue
            returns.append(cur / prev - 1.0)
        if len(returns) < 2:
            return 0.0
        mean = sum(returns) / len(returns)
        variance = sum((item - mean) ** 2 for item in returns) / max(1, (len(returns) - 1))
        std = math.sqrt(max(variance, 0.0))
        if std <= 1e-12:
            return 0.0
        return (mean / std) * math.sqrt(252)

    @staticmethod
    def _turnover(*, trades: list[dict[str, Any]], start_cash: float) -> float:
        if start_cash <= 0:
            return 0.0
        gross = 0.0
        for row in trades:
            gross += _to_float(row.get("price", 0.0), 0.0) * _to_float(row.get("quantity", 0.0), 0.0)
        return gross / start_cash
