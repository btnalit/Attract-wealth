# -*- coding: utf-8 -*-
"""
量价规则引擎：放量/缩量、量价配合、地量地价。

输入：context dict（含 technical_indicators 和 kline_recent）
输出：List[Signal]

注：完整量价规则需要历史序列，这里用 kline_recent（最近 30 日）判断。
"""
from __future__ import annotations

from typing import Any, Dict, List

from src.agents.rules.base import Signal


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        result = float(value)
        return result if result == result else default
    except (TypeError, ValueError):
        return default


def evaluate(context: Dict[str, Any]) -> List[Signal]:
    """评估量价类规则。需要 kline_recent 历史序列。"""
    signals: List[Signal] = []
    kline = context.get("kline_recent") or []
    if not isinstance(kline, list) or len(kline) < 5:
        return signals

    # 提取最近 5-10 日数据
    recent = kline[-10:] if len(kline) >= 10 else kline[-5:]
    if len(recent) < 5:
        return signals

    volumes = [_f(k.get("volume")) for k in recent]
    closes = [_f(k.get("close")) for k in recent]

    # 过滤掉 0 成交量（停牌日）
    valid_volumes = [v for v in volumes if v > 0]
    if len(valid_volumes) < 3:
        return signals

    avg_volume = sum(valid_volumes) / len(valid_volumes)
    latest_volume = volumes[-1]
    latest_close = closes[-1]
    prev_close = closes[-2] if len(closes) >= 2 else latest_close

    if avg_volume <= 0 or latest_volume <= 0:
        return signals

    # 规则 1：放量突破（成交量 > 均值 1.5 倍且价格上涨）
    vol_ratio = latest_volume / avg_volume
    price_chg = (latest_close - prev_close) / prev_close * 100 if prev_close > 0 else 0.0

    if vol_ratio >= 1.5 and price_chg > 0:
        strength = min(80.0, 60.0 + (vol_ratio - 1.5) * 20)
        signals.append(Signal(
            rule="VOLUME_BREAKOUT_UP",
            direction="BULL",
            strength=strength,
            description=f"放量上涨：成交量({latest_volume:.0f}) 是均量({avg_volume:.0f}) 的 {vol_ratio:.1f} 倍，涨幅 {price_chg:.1f}%",
            evidence={"latest_volume": latest_volume, "avg_volume": avg_volume, "vol_ratio": round(vol_ratio, 2), "price_chg_pct": round(price_chg, 2)},
            category="volume_price",
        ))
    elif vol_ratio >= 1.5 and price_chg < 0:
        strength = min(80.0, 60.0 + (vol_ratio - 1.5) * 20)
        signals.append(Signal(
            rule="VOLUME_BREAKOUT_DOWN",
            direction="BEAR",
            strength=strength,
            description=f"放量下跌：成交量({latest_volume:.0f}) 是均量({avg_volume:.0f}) 的 {vol_ratio:.1f} 倍，跌幅 {abs(price_chg):.1f}%",
            evidence={"latest_volume": latest_volume, "avg_volume": avg_volume, "vol_ratio": round(vol_ratio, 2), "price_chg_pct": round(price_chg, 2)},
            category="volume_price",
        ))

    # 规则 2：缩量回调（成交量 < 均值 0.7 倍）
    if vol_ratio <= 0.7 and abs(price_chg) < 2.0:
        # 缩量横盘：中性偏多（洗盘信号）
        signals.append(Signal(
            rule="LOW_VOLUME_CONSOLIDATION",
            direction="BULL",
            strength=52.0,
            description=f"缩量横盘：成交量仅为均量的 {vol_ratio:.1f} 倍，可能为主力洗盘",
            evidence={"latest_volume": latest_volume, "avg_volume": avg_volume, "vol_ratio": round(vol_ratio, 2)},
            category="volume_price",
        ))

    # 规则 3：地量地价（成交量创近 10 日新低 + 价格企稳）
    if len(valid_volumes) >= 5:
        min_vol = min(valid_volumes[:-1])  # 排除当日
        if latest_volume < min_vol * 0.9 and latest_volume > 0:
            signals.append(Signal(
                rule="EXTREME_LOW_VOLUME",
                direction="BULL",
                strength=60.0,
                description=f"地量信号：成交量创近期新低({latest_volume:.0f})，抛压枯竭，常见于底部",
                evidence={"latest_volume": latest_volume, "prev_min_volume": min_vol},
                category="volume_price",
            ))

    # 规则 4：量价背离（价涨量缩 或 价跌量增）
    if price_chg > 2.0 and vol_ratio < 0.8:
        signals.append(Signal(
            rule="VOLUME_PRICE_DIVERGENCE_BEAR",
            direction="BEAR",
            strength=62.0,
            description=f"量价背离：价格上涨 {price_chg:.1f}% 但成交量萎缩至 {vol_ratio:.1f} 倍，上涨乏力",
            evidence={"price_chg_pct": round(price_chg, 2), "vol_ratio": round(vol_ratio, 2)},
            category="volume_price",
        ))
    elif price_chg < -2.0 and vol_ratio > 1.3:
        signals.append(Signal(
            rule="VOLUME_PRICE_DIVERGENCE_PANIC",
            direction="BEAR",
            strength=68.0,
            description=f"恐慌性下跌：价格跌 {abs(price_chg):.1f}% 且放量至 {vol_ratio:.1f} 倍，抛压沉重",
            evidence={"price_chg_pct": round(price_chg, 2), "vol_ratio": round(vol_ratio, 2)},
            category="volume_price",
        ))

    return signals
