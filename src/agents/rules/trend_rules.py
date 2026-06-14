# -*- coding: utf-8 -*-
"""
趋势规则引擎：均线排列、金叉死叉、MACD 背离。

输入：technical_indicators dict（ChinaDataAssembler 产出）
输出：List[Signal]，每条信号含方向/强度/依据
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
    """评估趋势类规则。indicators 来自 context['technical_indicators']。"""
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

    # 规则 1：均线多头/空头排列
    # 多头排列：MA5 > MA10 > MA20（且都 > MA60 更强）
    # 空头排列：MA5 < MA10 < MA20
    if ma5 > 0 and ma10 > 0 and ma20 > 0:
        if ma5 > ma10 > ma20:
            strength = 60.0
            if ma60 > 0 and ma20 > ma60:
                strength = 80.0  # 完美多头排列
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
                strength = 80.0  # 完美空头排列
            signals.append(Signal(
                rule="MA_BEARISH_ALIGNMENT",
                direction="BEAR",
                strength=strength,
                description=f"均线空头排列 MA5({ma5:.2f})<MA10({ma10:.2f})<MA20({ma20:.2f})",
                evidence={"ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60},
                category="trend",
            ))

    # 规则 2：MA5/MA20 相对位置（金叉/死叉的近似）
    # 完整金叉死叉需要历史序列，这里用当前位置近似判断
    if ma5 > 0 and ma20 > 0:
        if ma5 > ma20:
            signals.append(Signal(
                rule="MA5_ABOVE_MA20",
                direction="BULL",
                strength=55.0,
                description=f"MA5({ma5:.2f}) 在 MA20({ma20:.2f}) 之上，短期趋势偏多",
                evidence={"ma5": ma5, "ma20": ma20},
                category="trend",
            ))
        else:
            signals.append(Signal(
                rule="MA5_BELOW_MA20",
                direction="BEAR",
                strength=55.0,
                description=f"MA5({ma5:.2f}) 在 MA20({ma20:.2f}) 之下，短期趋势偏空",
                evidence={"ma5": ma5, "ma20": ma20},
                category="trend",
            ))

    # 规则 3：MACD 柱状图方向（动能）
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

    # 规则 4：MACD DIF 与 DEA（信号线）位置
    if macd_dif != 0.0 and macd_signal != 0.0:
        if macd_dif > macd_signal:
            signals.append(Signal(
                rule="MACD_DIF_ABOVE_SIGNAL",
                direction="BULL",
                strength=58.0,
                description=f"MACD DIF({macd_dif:.3f}) 上穿信号线({macd_signal:.3f})",
                evidence={"macd_dif": macd_dif, "macd_signal": macd_signal},
                category="trend",
            ))
        else:
            signals.append(Signal(
                rule="MACD_DIF_BELOW_SIGNAL",
                direction="BEAR",
                strength=58.0,
                description=f"MACD DIF({macd_dif:.3f}) 下穿信号线({macd_signal:.3f})",
                evidence={"macd_dif": macd_dif, "macd_signal": macd_signal},
                category="trend",
            ))

    # 规则 5：价格与 MA60 关系（长期趋势）
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

    return signals
