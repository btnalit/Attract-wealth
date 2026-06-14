"""
来财 (Attract-wealth) — 风控软参数加载器。

加载 config/risk_limits.toml，作为 RiskGate 硬红线之外的"可调软规则"。

设计分层：
- 硬红线（不可配置、不可绕过）：在 src/execution/risk_gate.py 的类常量中
  （MAX_SINGLE_ORDER_RATIO / MAX_DAILY_LOSS_RATIO / MAX_POSITION_CONCENTRATION 等）
- 软规则（可配置、补充保护）：本文件加载的参数
  （总仓位 / 行业集中度 / 持股数 / 止损 / 止盈 / 大额预警）

软规则与硬红线一样在 check_order 中强制执行，区别仅在于"参数值可调"。
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 配置文件路径：优先环境变量 RISK_LIMITS_CONFIG，其次 config/risk_limits.toml
_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "risk_limits.toml"


@dataclass
class RiskLimits:
    """风控软参数（全部带安全默认值，配置缺失时仍提供基本保护）。

    语义：
    - max_total_position_ratio: 总持仓市值占总资产上限（>0 启用）
    - max_sector_ratio: 单行业持仓占总资产上限（>0 启用）
    - max_holding_count: 最大持股数量（>0 启用）
    - stop_loss_percent: 个股止损线（负数，如 -0.08 = -8%；达到即触发强卖建议）
    - take_profit_percent: 个股止盈线（正数，如 0.20 = +20%；达到即触发获利了结建议）
    - large_order_threshold: 大额交易预警阈值（元；>0 启用）
    """

    max_total_position_ratio: float = 0.80
    max_sector_ratio: float = 0.40
    max_holding_count: int = 10
    stop_loss_percent: float = -0.08
    take_profit_percent: float = 0.20
    large_order_threshold: float = 50000.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RiskLimits":
        """从 toml 解析后的 dict 构造。容忍缺失字段与类型错误，回退到默认。"""
        risk = data.get("risk", {}) if isinstance(data, dict) else {}
        alerts = data.get("alerts", {}) if isinstance(data, dict) else {}

        def _f(key: str, default: float, section: dict) -> float:
            try:
                v = section.get(key, default)
                return float(v) if v is not None else default
            except (TypeError, ValueError):
                logger.warning("risk_limits: invalid value for %s=%r, fallback to %s", key, section.get(key), default)
                return default

        def _i(key: str, default: int, section: dict) -> int:
            try:
                v = section.get(key, default)
                return int(v) if v is not None else default
            except (TypeError, ValueError):
                logger.warning("risk_limits: invalid value for %s=%r, fallback to %s", key, section.get(key), default)
                return default

        return cls(
            max_total_position_ratio=_f("max_total_position_ratio", cls.max_total_position_ratio, risk),
            max_sector_ratio=_f("max_sector_ratio", cls.max_sector_ratio, risk),
            max_holding_count=_i("max_holding_count", cls.max_holding_count, risk),
            stop_loss_percent=_f("stop_loss_percent", cls.stop_loss_percent, risk),
            take_profit_percent=_f("take_profit_percent", cls.take_profit_percent, risk),
            large_order_threshold=_f("large_order_threshold", cls.large_order_threshold, alerts),
        )

    @classmethod
    def defaults(cls) -> "RiskLimits":
        """安全默认值（配置文件缺失时使用）。"""
        return cls()


def load_risk_limits(config_path: str | Path | None = None) -> RiskLimits:
    """加载 risk_limits.toml。文件缺失或解析失败时回退到安全默认值。

    优先级：参数 config_path > 环境变量 RISK_LIMITS_CONFIG > config/risk_limits.toml > 默认值
    """
    path: Path | None = None
    if config_path:
        path = Path(config_path)
    else:
        env_path = os.getenv("RISK_LIMITS_CONFIG", "").strip()
        if env_path:
            path = Path(env_path)
        else:
            path = _DEFAULT_CONFIG_PATH

    if not path.exists():
        logger.warning("risk_limits config not found at %s, using defaults", path)
        return RiskLimits.defaults()

    try:
        import tomllib  # py311+

        with open(path, "rb") as f:
            data = tomllib.load(f)
        limits = RiskLimits.from_dict(data)
        logger.info(
            "risk_limits loaded from %s: total_pos<=%.0f%% sector<=%.0f%% holdings<=%d "
            "stop=%.1f%% profit=%.1f%% large>=%.0f",
            path,
            limits.max_total_position_ratio * 100,
            limits.max_sector_ratio * 100,
            limits.max_holding_count,
            limits.stop_loss_percent * 100,
            limits.take_profit_percent * 100,
            limits.large_order_threshold,
        )
        return limits
    except Exception as exc:  # noqa: BLE001
        logger.error("failed to load risk_limits from %s, using defaults: %s", path, exc)
        return RiskLimits.defaults()
