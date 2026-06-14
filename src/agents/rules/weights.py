# -*- coding: utf-8 -*-
"""
分析师权重配置 + 回测校准。

设计：
- 默认权重：技术面40 / 基本面30 / 情绪面20 / 资金面10
- 可被环境变量 ASHARE_ANALYST_WEIGHTS 覆盖（JSON 格式）
- calibrate_weights_from_backtest()：给定回测命中率，自动校准权重
  命中率高的类别权重上调，低的下调，归一化后返回

这样回测模块产出的命中率可以直接喂回权重系统，形成闭环。
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

logger = logging.getLogger(__name__)

# 默认权重（技术面 / 基本面 / 情绪面）
DEFAULT_WEIGHTS: Dict[str, float] = {
    "technical": 40.0,
    "fundamental": 30.0,
    "news": 20.0,
    "sentiment": 20.0,  # news 的别名
}


def get_calibrated_weights() -> Dict[str, float]:
    """获取当前生效的分析师权重。

    优先级：环境变量 ASHARE_ANALYST_WEIGHTS > 默认权重。
    环境变量格式：JSON dict，如 {"technical": 50, "fundamental": 25, "news": 25}
    """
    env_raw = os.getenv("ASHARE_ANALYST_WEIGHTS", "").strip()
    if env_raw:
        try:
            parsed = json.loads(env_raw)
            if isinstance(parsed, dict):
                # 归一化到总和 100
                total = sum(float(v) for v in parsed.values() if isinstance(v, (int, float)))
                if total > 0:
                    return {k: float(v) / total * 100.0 for k, v in parsed.items() if isinstance(v, (int, float))}
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("ASHARE_ANALYST_WEIGHTS 解析失败，使用默认权重: %s", exc)
    return dict(DEFAULT_WEIGHTS)


def calibrate_weights_from_backtest(
    hit_rates: Dict[str, float],
    *,
    base_weights: Dict[str, float] | None = None,
) -> Dict[str, float]:
    """根据回测命中率校准权重。

    策略：权重 ∝ base_weight × (0.5 + hit_rate)，命中率 50% 不变，
    命中率 100% 权重翻倍，命中率 0% 权重减半。最终归一化到 100。

    Args:
        hit_rates: {analyst_type: hit_rate(0-1)}，如 {"technical": 0.62, "fundamental": 0.55}
        base_weights: 基础权重（默认 DEFAULT_WEIGHTS）

    Returns:
        校准后的归一化权重 dict（总和=100）
    """
    base = dict(base_weights or DEFAULT_WEIGHTS)
    calibrated: Dict[str, float] = {}

    for analyst_type, base_w in base.items():
        hit_rate = hit_rates.get(analyst_type, 0.5)  # 默认 50%（中性）
        hit_rate = max(0.0, min(1.0, float(hit_rate)))
        # 调整因子：0.5 + hit_rate，范围 [0.5, 1.5]
        factor = 0.5 + hit_rate
        calibrated[analyst_type] = base_w * factor

    # 归一化到总和 100
    total = sum(calibrated.values())
    if total > 0:
        calibrated = {k: round(v / total * 100.0, 2) for k, v in calibrated.items()}

    return calibrated


def format_weights_for_env(weights: Dict[str, float]) -> str:
    """把权重 dict 格式化为环境变量字符串（供 calibrate 后写回 .env）。"""
    return json.dumps({k: round(v, 1) for k, v in weights.items()}, ensure_ascii=False)


def calibrate_from_online_accuracy(
    *,
    min_samples: int = 10,
    base_weights: Dict[str, float] | None = None,
) -> Dict[str, float] | None:
    """P2-1：用在线准确率（signal_log 实盘验证）校准权重。

    优先级高于离线回测，因为它反映的是当前市场状态下的真实命中率。
    若在线样本不足（< min_samples），返回 None 表示无法校准，调用方应回退。

    Returns:
        校准后的权重 dict，或 None（样本不足/DAO 失败）
    """
    try:
        from src.agents.rules.online_tracker import get_online_hit_rates
        from src.agents.rules.trend_rules import TREND_RULE_NAMES

        rule_rates_raw = get_online_hit_rates(min_samples=min_samples)
        if not rule_rates_raw:
            return None

        # 把按规则的命中率聚合到按分析师：trend 规则族 → technical 分析师
        tech_rates = [
            info["hit_rate"] for rule, info in rule_rates_raw.items()
            if rule in TREND_RULE_NAMES
        ]
        if not tech_rates:
            return None

        analyst_rates = {
            "technical": sum(tech_rates) / len(tech_rates),
            "fundamental": 0.5,
            "news": 0.5,
            "sentiment": 0.5,
        }
        return calibrate_weights_from_backtest(analyst_rates, base_weights=base_weights)
    except Exception as exc:  # noqa: BLE001
        logger.debug("在线准确率校准失败（已忽略）: %s", exc)
        return None
