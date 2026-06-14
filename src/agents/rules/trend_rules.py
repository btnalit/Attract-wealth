# -*- coding: utf-8 -*-
"""
趋势规则引擎：均线排列、金叉死叉穿越、RSI 超买超卖、MACD 背离。

提供两个入口：
- evaluate(indicators): 单点指标规则（排列、价格位置、动能），向后兼容
- evaluate_with_history(kline_recent): 序列规则（金叉穿越、RSI、MACD背离），
  需要 kline_recent 历史序列（ChinaDataAssembler 产出的最近 30 日）

technical.py 应同时调用两者，合并信号。
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


def evaluate(indicators: Dict[str, Any]) -> List[Signal]:
    """单点指标规则（均线排列、价格与MA60、MACD动能/位置）。

    这些规则只需最新一行指标即可判断，不依赖历史序列。
    """
    signals: List[Signal] = []
    if not indicators:
        return signals

    ma5 = _f(indicators.get("MA5"))
    ma10 = _f(indicators.get("MA10"))
    ma20 = _f(indicators.get("MA20"))
    ma60 = _f(indicators.get("MA60"))
    macd_dif = _f(indicators.get("MACD_DIF"))
    macd_hist = _f(indicators.get("MACD_HIST"))
    macd_signal = _f(indicators.get("MACD_SIGNAL"))
    close = _f(indicators.get("close", indicators.get("CLOSE")))
    rsi = _f(indicators.get("RSI_14"))

    # 规则 1：均线多头/空头排列（单点，仍有效）
    if ma5 > 0 and ma10 > 0 and ma20 > 0:
        if ma5 > ma10 > ma20:
            strength = 60.0
            if ma60 > 0 and ma20 > ma60:
                strength = 80.0
            signals.append(Signal(
                rule="MA_BULLISH_ALIGNMENT",
                direction="BULL",
                strength=strength,
                description=f"均线多头排列 MA5({ma5:.2f})>MA10({ma10:.2f})>MA20({ma20:.2f})",
                evidence={"ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60},
                category="trend",
            ))
        elif ma5 < ma10 < ma20:
            strength = 60.0
            if ma60 > 0 and ma20 < ma60:
                strength = 80.0
            signals.append(Signal(
                rule="MA_BEARISH_ALIGNMENT",
                direction="BEAR",
                strength=strength,
                description=f"均线空头排列 MA5({ma5:.2f})<MA10({ma10:.2f})<MA20({ma20:.2f})",
                evidence={"ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60},
                category="trend",
            ))

    # 规则 2：MACD 柱状图动能（单点）
    if macd_hist != 0.0:
        if macd_hist > 0:
            signals.append(Signal(
                rule="MACD_HIST_POSITIVE",
                direction="BULL",
                strength=min(70.0, 50.0 + abs(macd_hist) * 20),
                description=f"MACD 柱状图为正({macd_hist:.3f})，多头动能",
                evidence={"macd_hist": macd_hist},
                category="trend",
            ))
        else:
            signals.append(Signal(
                rule="MACD_HIST_NEGATIVE",
                direction="BEAR",
                strength=min(70.0, 50.0 + abs(macd_hist) * 20),
                description=f"MACD 柱状图为负({macd_hist:.3f})，空头动能",
                evidence={"macd_hist": macd_hist},
                category="trend",
            ))

    # 规则 3：价格与 MA60 关系（长期趋势，单点）
    if close > 0 and ma60 > 0:
        if close > ma60:
            deviation = (close - ma60) / ma60 * 100
            strength = min(75.0, 55.0 + deviation)
            signals.append(Signal(
                rule="PRICE_ABOVE_MA60",
                direction="BULL",
                strength=strength,
                description=f"收盘价({close:.2f}) 站上 MA60({ma60:.2f})，长期趋势向上 (+{deviation:.1f}%)",
                evidence={"close": close, "ma60": ma60, "deviation_pct": round(deviation, 2)},
                category="trend",
            ))
        else:
            deviation = (ma60 - close) / ma60 * 100
            strength = min(75.0, 55.0 + deviation)
            signals.append(Signal(
                rule="PRICE_BELOW_MA60",
                direction="BEAR",
                strength=strength,
                description=f"收盘价({close:.2f}) 跌破 MA60({ma60:.2f})，长期趋势向下 (-{deviation:.1f}%)",
                evidence={"close": close, "ma60": ma60, "deviation_pct": round(-deviation, 2)},
                category="trend",
            ))

    # 规则 4：RSI 超买超卖（单点，之前缺失）
    if rsi > 0:
        if rsi >= 70:
            signals.append(Signal(
                rule="RSI_OVERBOUGHT",
                direction="BEAR",
                strength=min(80.0, 60.0 + (rsi - 70) * 2),
                description=f"RSI={rsi:.1f} 超买(>=70)，短期有回调风险",
                evidence={"rsi": rsi},
                category="trend",
            ))
        elif rsi <= 30:
            signals.append(Signal(
                rule="RSI_OVERSOLD",
                direction="BULL",
                strength=min(80.0, 60.0 + (30 - rsi) * 2),
                description=f"RSI={rsi:.1f} 超卖(<=30)，短期有反弹机会",
                evidence={"rsi": rsi},
                category="trend",
            ))

    return signals


def evaluate_with_history(kline_recent: List[Dict[str, Any]]) -> List[Signal]:
    """序列规则：需要历史 K 线的穿越/背离检测。

    Args:
        kline_recent: 最近 N 日 K 线序列，每条含 close/ma5/ma20 等字段

    包含规则：
    - MA5/MA20 金叉死叉（穿越事件，非相对位置）
    - MACD 金叉死叉（DIF 穿越 signal）
    - MACD 顶背离/底背离（价格与 MACD 极值比较）
    """
    signals: List[Signal] = []
    if not kline_recent or len(kline_recent) < 3:
        return signals

    # 取最近几日数据做穿越检测（需至少前一日+今日）
    closes = [_f(k.get("close")) for k in kline_recent]
    ma5_list = [_f(k.get("ma5")) for k in kline_recent]
    ma20_list = [_f(k.get("ma20")) for k in kline_recent]

    # ===== 规则 5：MA5/MA20 金叉死叉（穿越事件）=====
    signals.extend(_detect_ma_cross(ma5_list, ma20_list, closes))

    # ===== 规则 6：MACD 金叉死叉 + 背离 =====
    # kline_recent 可能不含 macd 列，这里用 close 近似计算 MACD 序列
    if len(closes) >= 26:
        macd_signals = _detect_macd_signals(closes)
        signals.extend(macd_signals)

    return signals


def _detect_ma_cross(
    ma5_list: List[float],
    ma20_list: List[float],
    closes: List[float],
) -> List[Signal]:
    """检测 MA5/MA20 金叉死叉（穿越事件）。

    金叉：前一日 MA5 <= MA20，今日 MA5 > MA20
    死叉：前一日 MA5 >= MA20，今日 MA5 < MA20
    """
    signals: List[Signal] = []
    n = len(ma5_list)
    if n < 2:
        return signals

    # 检测最近一次穿越（从后往前扫，最多看 10 日）
    for i in range(n - 1, max(n - 11, 1) - 1, -1):
        prev_ma5, curr_ma5 = ma5_list[i - 1], ma5_list[i]
        prev_ma20, curr_ma20 = ma20_list[i - 1], ma20_list[i]
        if prev_ma5 <= 0 or prev_ma20 <= 0 or curr_ma5 <= 0 or curr_ma20 <= 0:
            continue

        # 金叉：从下方上穿
        if prev_ma5 <= prev_ma20 and curr_ma5 > curr_ma20:
            days_ago = n - 1 - i  # 0 = 今日发生
            strength = max(50.0, 75.0 - days_ago * 5)  # 越新越强
            signals.append(Signal(
                rule="MA_GOLDEN_CROSS",
                direction="BULL",
                strength=strength,
                description=f"MA5 上穿 MA20 形成金叉（{days_ago + 1}日前），MA5={curr_ma5:.2f} MA20={curr_ma20:.2f}",
                evidence={"ma5": curr_ma5, "ma20": curr_ma20, "days_ago": days_ago},
                category="trend",
            ))
            break  # 只取最近一次

    for i in range(n - 1, max(n - 11, 1) - 1, -1):
        prev_ma5, curr_ma5 = ma5_list[i - 1], ma5_list[i]
        prev_ma20, curr_ma20 = ma20_list[i - 1], ma20_list[i]
        if prev_ma5 <= 0 or prev_ma20 <= 0 or curr_ma5 <= 0 or curr_ma20 <= 0:
            continue

        # 死叉：从上方下穿
        if prev_ma5 >= prev_ma20 and curr_ma5 < curr_ma20:
            days_ago = n - 1 - i
            strength = max(50.0, 75.0 - days_ago * 5)
            signals.append(Signal(
                rule="MA_DEATH_CROSS",
                direction="BEAR",
                strength=strength,
                description=f"MA5 下穿 MA20 形成死叉（{days_ago + 1}日前），MA5={curr_ma5:.2f} MA20={curr_ma20:.2f}",
                evidence={"ma5": curr_ma5, "ma20": curr_ma20, "days_ago": days_ago},
                category="trend",
            ))
            break

    return signals


def _detect_macd_signals(closes: List[float]) -> List[Signal]:
    """检测 MACD 金叉死叉 + 顶底背离。

    用 close 序列近似计算 EMA12/EMA26/DIF/DEA，做穿越和极值比较。
    """
    signals: List[Signal] = []
    n = len(closes)
    if n < 35:  # 需要 EMA26 收敛 + 9日DEA
        return signals

    # 计算 EMA12 / EMA26
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    dif = [a - b for a, b in zip(ema12, ema26)]
    # DEA = DIF 的 9日EMA
    dea = _ema(dif, 9)
    macd_hist = [(d - e) * 2 for d, e in zip(dif, dea)]  # MACD柱 = (DIF-DEA)*2

    # ===== MACD 金叉死叉 =====
    # 从后往前扫最近一次穿越
    for i in range(n - 1, max(n - 6, 1) - 1, -1):
        if dif[i - 1] <= dea[i - 1] and dif[i] > dea[i]:
            signals.append(Signal(
                rule="MACD_GOLDEN_CROSS",
                direction="BULL",
                strength=max(55.0, 75.0 - (n - 1 - i) * 8),
                description=f"MACD DIF 上穿 DEA 形成金叉，DIF={dif[i]:.3f} DEA={dea[i]:.3f}",
                evidence={"dif": round(dif[i], 4), "dea": round(dea[i], 4)},
                category="trend",
            ))
            break
    for i in range(n - 1, max(n - 6, 1) - 1, -1):
        if dif[i - 1] >= dea[i - 1] and dif[i] < dea[i]:
            signals.append(Signal(
                rule="MACD_DEATH_CROSS",
                direction="BEAR",
                strength=max(55.0, 75.0 - (n - 1 - i) * 8),
                description=f"MACD DIF 下穿 DEA 形成死叉，DIF={dif[i]:.3f} DEA={dea[i]:.3f}",
                evidence={"dif": round(dif[i], 4), "dea": round(dea[i], 4)},
                category="trend",
            ))
            break

    # ===== MACD 顶背离/底背离 =====
    # 找近 30 日内价格的两个高点/低点，比较对应 MACD 值
    window = min(n, 30)
    signals.extend(_detect_divergence(closes[-window:], dif[-window:], macd_hist[-window:]))

    return signals


def _detect_divergence(closes: List[float], dif: List[float], macd_hist: List[float]) -> List[Signal]:
    """检测 MACD 顶背离/底背离。

    顶背离：价格创新高，但 MACD(DIF) 没创新高 → 看跌
    底背离：价格创新低，但 MACD(DIF) 没创新低 → 看涨
    """
    signals: List[Signal] = []
    n = len(closes)
    if n < 10:
        return signals

    # 找局部极值点（比左右相邻都大/小）
    highs: List[int] = []  # 索引
    lows: List[int] = []
    for i in range(2, n - 2):
        if closes[i] > closes[i - 1] and closes[i] > closes[i + 1] and closes[i] > closes[i - 2] and closes[i] > closes[i + 2]:
            highs.append(i)
        if closes[i] < closes[i - 1] and closes[i] < closes[i + 1] and closes[i] < closes[i - 2] and closes[i] < closes[i + 2]:
            lows.append(i)

    # 顶背离：取最近两个高点
    if len(highs) >= 2:
        h1, h2 = highs[-2], highs[-1]
        if closes[h2] > closes[h1] and dif[h2] < dif[h1]:
            signals.append(Signal(
                rule="MACD_TOP_DIVERGENCE",
                direction="BEAR",
                strength=70.0,
                description=f"MACD 顶背离：价格新高({closes[h2]:.2f}>{closes[h1]:.2f})但 DIF 未新高({dif[h2]:.3f}<{dif[h1]:.3f})，上涨动能衰竭",
                evidence={"price_high1": closes[h1], "price_high2": closes[h2], "dif_high1": round(dif[h1], 4), "dif_high2": round(dif[h2], 4)},
                category="trend",
            ))

    # 底背离：取最近两个低点
    if len(lows) >= 2:
        l1, l2 = lows[-2], lows[-1]
        if closes[l2] < closes[l1] and dif[l2] > dif[l1]:
            signals.append(Signal(
                rule="MACD_BOTTOM_DIVERGENCE",
                direction="BULL",
                strength=70.0,
                description=f"MACD 底背离：价格新低({closes[l2]:.2f}<{closes[l1]:.2f})但 DIF 未新低({dif[l2]:.3f}>{dif[l1]:.3f})，下跌动能衰竭",
                evidence={"price_low1": closes[l1], "price_low2": closes[l2], "dif_low1": round(dif[l1], 4), "dif_low2": round(dif[l2], 4)},
                category="trend",
            ))

    return signals


def _ema(values: List[float], period: int) -> List[float]:
    """计算 EMA 序列（与 pandas ewm span=period adjust=False 一致）。"""
    if not values:
        return []
    alpha = 2.0 / (period + 1)
    result = [values[0]]
    for i in range(1, len(values)):
        result.append(alpha * values[i] + (1 - alpha) * result[-1])
    return result
