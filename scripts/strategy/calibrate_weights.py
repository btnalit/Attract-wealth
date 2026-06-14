# -*- coding: utf-8 -*-
"""回测校准分析师权重 (P1-1)。

把规则引擎的回测命中率回喂到分析师权重系统，形成闭环：

    历史 K 线  ──▶  backtest_trend_signals  ──▶  按规则命中率
                                                      │
                                                      ▼
                              calibrate_weights_from_backtest
                                                      │
                                                      ▼
                              写入 ASHARE_ANALYST_WEIGHTS 环境变量

用法：
    # 对单只标的回测并打印建议权重
    python scripts/strategy/calibrate_weights.py --ticker 000001

    # 回测后直接写回 .env
    python scripts/strategy/calibrate_weights.py --ticker 000001 --write-env

    # 用多只标的聚合命中率（更稳健）
    python scripts/strategy/calibrate_weights.py --tickers 000001,600519,000858

无网络/无 K 线时，脚本会以 0.5 中性命中率产出默认权重并退出（非零码），
便于 CI 中作为"可运行但无需真实数据"的冒烟节点。
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pandas as pd  # noqa: E402

from src.agents.rules.backtest import backtest_trend_signals  # noqa: E402
from src.agents.rules.weights import (  # noqa: E402
    DEFAULT_WEIGHTS,
    calibrate_weights_from_backtest,
    format_weights_for_env,
    get_calibrated_weights,
)

logger = logging.getLogger("calibrate_weights")


def _fetch_kline(ticker: str, limit: int = 250) -> pd.DataFrame:
    """通过 ChinaDataAssembler 的多源管理器拉取历史 K 线。"""
    try:
        from src.dataflows.china_data import ChinaDataAssembler

        assembler = ChinaDataAssembler()
        df = assembler._get_kline(ticker, limit=limit)
        if isinstance(df, pd.DataFrame) and not df.empty:
            return df
    except Exception as exc:  # noqa: BLE001
        logger.warning("拉取 %s K 线失败: %s", ticker, exc)
    return pd.DataFrame()


def _enrich_with_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """对历史 K 线计算技术指标（backtest 需要 sma_*/macd_* 列）。"""
    try:
        from src.dataflows.technical.indicators import PandasTaIndicatorEngine

        engine = PandasTaIndicatorEngine()
        enriched = engine.calculate_all(df)
        if isinstance(enriched, pd.DataFrame) and not enriched.empty:
            return enriched
    except Exception as exc:  # noqa: BLE001
        logger.warning("技术指标计算失败，使用原始 K 线: %s", exc)
    return df


def _hit_rates_to_analyst(hit_rate_by_rule: dict[str, float]) -> dict[str, float]:
    """把按 *规则* 的命中率聚合到按 *分析师* 的命中率。

    映射策略（A 股规则引擎目前只有 trend 规则族，故把 trend 的命中率
    视作 technical 分析师的命中率；其它分析师保持中性 0.5）：
        - technical ← trend 类规则的命中均值
        - fundamental / news / sentiment ← 0.5（无对应规则，保持中性）

    随着规则引擎扩展到基本面/情绪面，可在本函数补全对应映射。
    """
    tech_rates = [r for rule, r in hit_rate_by_rule.items() if "trend" in _rule_category(rule)]
    technical = sum(tech_rates) / len(tech_rates) if tech_rates else 0.5

    return {
        "technical": technical,
        "fundamental": 0.5,
        "news": 0.5,
        "sentiment": 0.5,
    }


def _rule_category(rule: str) -> str:
    """根据规则名推断类别（用于把命中率归类到分析师）。"""
    trend_rules = {
        "MA_BULLISH_ALIGNMENT", "MA_BEARISH_ALIGNMENT",
        "MACD_HIST_POSITIVE", "MACD_HIST_NEGATIVE",
        "PRICE_ABOVE_MA60", "PRICE_BELOW_MA60",
        "RSI_OVERBOUGHT", "RSI_OVERSOLD",
        "MA_GOLDEN_CROSS", "MA_DEATH_CROSS",
        "MACD_GOLDEN_CROSS", "MACD_DEATH_CROSS",
        "MACD_TOP_DIVERGENCE", "MACD_BOTTOM_DIVERGENCE",
    }
    return "trend" if rule in trend_rules else "other"


def calibrate_from_tickers(
    tickers: list[str],
    *,
    forward_days: int = 5,
    min_strength: float = 55.0,
) -> tuple[dict[str, float], dict[str, Any]]:
    """对多只标的回测，聚合命中率后校准权重。

    Returns:
        (calibrated_weights, meta) —— meta 含原始命中率、回测样本量等。
    """
    rule_hits: dict[str, list[float]] = {}
    total_records = 0
    overall_hits = 0

    for ticker in tickers:
        df = _fetch_kline(ticker, limit=250)
        if df is None or df.empty:
            logger.warning("[%s] 无 K 线数据，跳过", ticker)
            continue
        df = _enrich_with_indicators(df)
        result = backtest_trend_signals(
            df, forward_days=forward_days, min_strength=min_strength
        )
        by_rule = result.get("summary", {}).get("by_rule", {})
        for rule, info in by_rule.items():
            rate = float(info.get("hit_rate", 0.0))
            rule_hits.setdefault(rule, []).append(rate)
        total_records += int(result.get("summary", {}).get("total_signals", 0))
        overall_hits += int(result.get("summary", {}).get("hit_count", 0))
        logger.info(
            "[%s] 样本 %d, 命中率 %.3f",
            ticker,
            result.get("summary", {}).get("total_signals", 0),
            result.get("summary", {}).get("hit_rate", 0.0),
        )

    if not rule_hits:
        logger.warning("未回测出任何信号，使用默认中性命中率 (0.5)")
        analyst_rates = {k: 0.5 for k in DEFAULT_WEIGHTS}
        meta = {"sample_records": 0, "overall_hit_rate": 0.0, "by_rule": {}, "tickers": tickers}
    else:
        rule_rate_avg = {rule: sum(rs) / len(rs) for rule, rs in rule_hits.items()}
        analyst_rates = _hit_rates_to_analyst(rule_rate_avg)
        meta = {
            "sample_records": total_records,
            "overall_hit_rate": round(overall_hits / total_records, 4) if total_records else 0.0,
            "by_rule": {k: round(v, 4) for k, v in rule_rate_avg.items()},
            "tickers": tickers,
        }

    calibrated = calibrate_weights_from_backtest(analyst_rates)
    meta["analyst_hit_rates"] = {k: round(v, 4) for k, v in analyst_rates.items()}
    return calibrated, meta


def _update_env_file(env_path: Path, weights_env_str: str) -> bool:
    """把 ASHARE_ANALYST_WEIGHTS 写入 .env（存在则替换，不存在则追加）。"""
    if not env_path.exists():
        env_path.write_text(
            f"ASHARE_ANALYST_WEIGHTS={weights_env_str}\n", encoding="utf-8"
        )
        return True

    lines = env_path.read_text(encoding="utf-8").splitlines()
    key = "ASHARE_ANALYST_WEIGHTS"
    found = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(key + "=") or stripped.startswith("# " + key + "="):
            lines[i] = f"{key}={weights_env_str}"
            found = True
            break
    if not found:
        lines.append(f"{key}={weights_env_str}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="用回测命中率校准分析师权重")
    parser.add_argument("--ticker", default="", help="单个标的代码")
    parser.add_argument(
        "--tickers", default="",
        help="多个标的（逗号分隔），命中率会被聚合平均",
    )
    parser.add_argument("--forward-days", type=int, default=5, help="未来收益天数（默认 5）")
    parser.add_argument("--min-strength", type=float, default=55.0, help="只统计强度>=此值的信号")
    parser.add_argument(
        "--write-env", action="store_true",
        help="把结果写回 .env（默认仅打印）",
    )
    parser.add_argument("--env-file", default=".env", help="目标 env 文件路径")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    tickers: list[str] = []
    if args.tickers:
        tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
    if args.ticker:
        tickers.append(args.ticker.strip())
    if not tickers:
        # 无标的时仍可演示校准流程（用中性命中率）
        logger.warning("未提供 --ticker/--tickers，将以中性命中率 (0.5) 演示校准流程")
        tickers = []

    calibrated, meta = calibrate_from_tickers(
        tickers, forward_days=args.forward_days, min_strength=args.min_strength
    )

    env_str = format_weights_for_env(calibrated)
    print("\n========== 权重校准结果 ==========")
    print(f"输入标的      : {tickers or '(none)'}")
    print(f"回测样本数    : {meta.get('sample_records', 0)}")
    print(f"总体命中率    : {meta.get('overall_hit_rate', 0.0):.3f}")
    print(f"分析师命中率  : {meta.get('analyst_hit_rates', {})}")
    print(f"按规则命中率  : {meta.get('by_rule', {})}")
    print(f"校准后权重    : {calibrated}")
    print(f"当前生效权重  : {get_calibrated_weights()}")
    print(f"\n建议环境变量  :")
    print(f"  ASHARE_ANALYST_WEIGHTS={env_str}")

    if args.write_env:
        env_path = (ROOT_DIR / args.env_file).resolve()
        updated = _update_env_file(env_path, env_str)
        print(f"\n已写入 {env_path} ({'更新已有项' if updated else '新增'})")

    # 无样本时返回 2，便于上游区分"演示输出"与"真实校准"
    return 0 if meta.get("sample_records", 0) > 0 else 2


if __name__ == "__main__":
    sys.exit(main())
