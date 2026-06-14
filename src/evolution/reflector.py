# -*- coding: utf-8 -*-
"""
来财 (Attract-wealth) — 自动反思框架 (Trading Reflector)

职责:
  - Observe: 采集交易数据、日志、Agent 响应
  - Orient: 分析偏差原因（模型幻觉、滑点、风控等）
  - Decide: 生成策略诊断报告与进化建议
  - Act: 触发 StrategyEvolver 进行进化并更新记忆
"""

import asyncio
import calendar
import logging
import time
from datetime import datetime, timedelta, date as date_type, timezone
from dataclasses import dataclass, field
from typing import Any, List, Dict, Optional
from pydantic import BaseModel, Field

from src.core.trading_ledger import TradingLedger, TradeRecord, LedgerEntry
from src.core.strategy_store import StrategyStore
from src.evolution.strategy_evolver import StrategyEvolver, DiagnosisReport, EvolutionMode

logger = logging.getLogger(__name__)

@dataclass
class ObservationData:
    """采集到的原始交易与执行数据"""
    date: str
    trades: List[Dict[str, Any]]
    ledger_entries: List[Dict[str, Any]]
    agent_logs: List[Dict[str, Any]]
    portfolio_snapshot: Dict[str, Any]

class OrientationReport(BaseModel):
    """偏差分析报告"""
    date: str
    metrics: Dict[str, Any]
    deviations: List[str]
    root_causes: List[Dict[str, Any]] = Field(default_factory=list)
    expected_pnl: float
    actual_pnl: float

class ReflectionReport(BaseModel):
    """最终反思报告"""
    date: str
    total_trades: int
    pnl: float
    win_rate: float
    deviations: List[str]
    strategy_adjustments: List[str]
    evolved_strategies: List[str]
    memory_updates: List[str]
    next_day_focus: str

class TradingReflector:
    """自动反思框架 — OODA 循环实现"""

    def __init__(
        self, 
        ledger: TradingLedger, 
        strategy_store: StrategyStore, 
        evolver: StrategyEvolver, 
        memory_manager: Any, 
        llm_client: Any = None
    ):
        self.ledger = ledger
        self.strategy_store = strategy_store
        self.evolver = evolver
        self.memory_manager = memory_manager
        self.llm_client = llm_client
        logger.info("TradingReflector initialized.")

    async def daily_reflection(self, target_date: str = None) -> ReflectionReport:
        """
        每日收盘后自动反思入口
        :param target_date: YYYY-MM-DD 格式日期，默认为今天
        """
        if not target_date:
            target_date = datetime.now().strftime("%Y-%m-%d")
        
        logger.info(f"Starting daily reflection for {target_date}...")

        # 1. Observe
        obs_data = self._observe(target_date)
        
        # 2. Orient
        orient_report = self._orient(obs_data)
        
        # 3. Decide
        diagnoses = self._decide(orient_report)
        
        # 4. Act
        report = await self._act(diagnoses, orient_report)
        
        logger.info(f"Reflection completed for {target_date}. PnL: {report.pnl}, Win Rate: {report.win_rate}")
        return report

    def _observe(self, date_str: str) -> ObservationData:
        """采集当日交易数据

        G7-8：使用本地时区的午夜作为过滤窗口边界。ledger 写入用 time.time()
        （本地时区的 epoch），这里也用本地时区解析 date_str，保持一致。
        显式构造 naive datetime 再取 timestamp() 与 ledger 的 time.time()
        行为一致（都按本地时区解释）。
        """
        # 计算时间戳范围（本地时区，与 ledger 的 time.time() 一致）
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        start_ts = dt.timestamp()
        end_ts = (dt + timedelta(days=1)).timestamp()

        # 从 Ledger 采集全天成交记录
        # 注意：TradingLedger 目前没有按时间过滤的公开方法，这里使用通用 list 并过滤
        all_trades = self.ledger.list_ledger_entries(category="TRADE", limit=1000)
        day_trades = [t for t in all_trades if start_ts <= t['timestamp'] < end_ts]

        # 采集 Agent 响应日志与系统日志
        all_entries = self.ledger.list_ledger_entries(limit=2000)
        day_entries = [e for e in all_entries if start_ts <= e['timestamp'] < end_ts]

        agent_logs = [e for e in day_entries if e['category'] in ("ANALYSIS", "AGENT")]

        # 采集决策链证据
        decision_evidence = self.ledger.list_decision_evidence(limit=500)
        day_evidence = [ev for ev in decision_evidence if start_ts <= ev['timestamp'] < end_ts]

        # 计算当日 P&L 与持仓快照
        portfolio = self.ledger.build_portfolio_snapshot()

        return ObservationData(
            date=date_str,
            trades=day_trades,
            ledger_entries=day_entries,
            agent_logs=agent_logs,
            portfolio_snapshot=portfolio
        )

    def _orient(self, data: ObservationData) -> OrientationReport:
        """分析偏差原因"""
        # 基础指标统计
        total_trades = len(data.trades)

        # G7-5：trade 记录的 metadata 不一定有 pnl 字段（依赖 broker 是否回填）。
        # 改为优先用 portfolio 快照的 realized_pnl 作为当日 P&L 真值；
        # trade 级别胜负只统计明确带 pnl 的记录，避免把"无 pnl=0"误算成平局。
        actual_pnl = 0.0
        portfolio = data.portfolio_snapshot or {}
        if isinstance(portfolio, dict):
            actual_pnl = float(portfolio.get("realized_pnl", 0.0) or 0.0)

        winning_trades = 0
        scored_trades = 0
        for t in data.trades:
            meta = t.get('metadata', {}) if isinstance(t.get('metadata'), dict) else {}
            if "pnl" in meta:
                scored_trades += 1
                if float(meta.get('pnl', 0) or 0) > 0:
                    winning_trades += 1
        # 仅在至少一笔带 pnl 时才算胜率，否则置 0（数据不足）
        win_rate = (winning_trades / scored_trades) if scored_trades > 0 else 0.0

        # 识别偏差来源 (简单规则 + 占位 LLM)
        deviations = []
        root_causes = []

        # 检查滑点 (Slippage)
        for t in data.trades:
            meta = t.get('metadata', {}) if isinstance(t.get('metadata'), dict) else {}
            price = float(meta.get('price', 0) or 0)
            filled_price = float(meta.get('filled_price', 0) or 0)
            if price > 0 and filled_price > 0:
                slippage = abs(filled_price - price) / price
                if slippage > 0.005: # > 0.5%
                    deviations.append(f"High slippage on {meta.get('trade_id')}: {round(slippage*100, 2)}%")

        # TODO: 使用 LLM 深度分析日志中的逻辑偏差 (幻觉或错误触发)
        if self.llm_client:
            # llm_analysis = self._call_llm_for_analysis(data)
            # deviations.extend(llm_analysis.get('deviations', []))
            pass

        return OrientationReport(
            date=data.date,
            metrics={
                "total_trades": total_trades,
                "scored_trades": scored_trades,
                "win_rate": win_rate,
                "actual_pnl": actual_pnl
            },
            deviations=list(set(deviations)),
            root_causes=root_causes,
            expected_pnl=0.0, # 理想情况
            actual_pnl=actual_pnl
        )

    def _decide(self, report: OrientationReport) -> List[DiagnosisReport]:
        """生成策略调整建议"""
        diagnoses = []
        
        # 如果当日出现严重偏差，触发策略修复或派生
        for dev in report.deviations:
            if "slippage" in dev.lower():
                # 针对滑点大，建议调整执行策略或价格敏感度
                # 寻找关联策略 (目前简化处理)
                active_strategies = self.strategy_store.list_strategy_versions(status="active")
                for s in active_strategies:
                    diagnoses.append(DiagnosisReport(
                        strategy_name=s['name'],
                        strategy_content=s.get('content', ''),
                        mode=EvolutionMode.DERIVED,
                        issues=[{"title": "High Slippage", "description": dev}],
                        context={"derive_direction": "降低价格敏感度，增加滑点容忍度或调整撮合逻辑"}
                    ))
        
        # 如果胜率过低，触发全方位反思
        # 注意：win_rate 基于"带 pnl 字段的成交"（scored_trades）；
        # total_trades 为全部成交笔数（含未回填 pnl 的），用于判断样本是否充足。
        if report.metrics['win_rate'] < 0.4 and report.metrics['total_trades'] > 5:
            active_strategies = self.strategy_store.list_strategy_versions(status="active")
            for s in active_strategies:
                 diagnoses.append(DiagnosisReport(
                        strategy_name=s['name'],
                        strategy_content=s.get('content', ''),
                        mode=EvolutionMode.FIX,
                        issues=[{"title": "Low Win Rate", "description": f"Current win rate {report.metrics['win_rate']} is below threshold."}]
                    ))
                    
        return diagnoses

    async def _act(self, diagnoses: List[DiagnosisReport], orient_report: OrientationReport) -> ReflectionReport:
        """执行进化并生成反思报告"""
        evolved_list = []
        adjustments = []
        memory_updates = []
        
        for diag in diagnoses:
            try:
                # G7-4：evolver.evolve() 内部 _call_llm 是同步阻塞网络调用，
                # 在 async 路径里必须用 to_thread 包装，避免阻塞事件循环。
                result = await asyncio.to_thread(self.evolver.evolve, diag)
                evolved_list.append(result.child_name)
                adjustments.append(f"Evolved {diag.strategy_name} -> {result.child_name}")

                # 更新策略 Quality Score
                # QA FIX L219: update_strategy_metrics 需要 strategy_id (UUID), not name
                strategies = self.strategy_store.list_strategy_versions(name=diag.strategy_name)
                if strategies:
                    strategy_id = strategies[0]["id"]
                    self.strategy_store.update_strategy_metrics(strategy_id, {"quality_score": 0.8}, merge=True)
                    adjustments.append(f"Updated quality score for {diag.strategy_name} (id={strategy_id})")
                else:
                    logger.warning(f"Strategy '{diag.strategy_name}' not found in store, skipping metric update")

            except Exception as e:
                logger.error(f"Failed to evolve strategy {diag.strategy_name}: {e}")

        # 将反思结果写入记忆系统
        reflection_summary = f"Date: {orient_report.date}, PnL: {orient_report.actual_pnl}, Deviations: {len(orient_report.deviations)}"
        # QA FIX L227: use memory_manager.write() instead of non-existent update_memory()
        # G7-4：memory_manager.write 是同步 sqlite 操作，用 to_thread 避免阻塞事件循环
        if self.memory_manager:
            await asyncio.to_thread(
                self.memory_manager.write,
                "warm",
                reflection_summary,
                ["daily_reflection", orient_report.date],
            )
            memory_updates.append("Wrote daily_reflection to WARM memory")

        # 写入 Ledger 作为系统记录（同步 sqlite，单次写入 <1ms，可接受）
        self.ledger.record_entry(LedgerEntry(
            category="EVOLUTION",
            action="DAILY_REFLECTION",
            detail=reflection_summary,
            status="success",
            metadata={"evolved_strategies": evolved_list}
        ))

        return ReflectionReport(
            date=orient_report.date,
            total_trades=orient_report.metrics['total_trades'],
            pnl=orient_report.actual_pnl,
            win_rate=orient_report.metrics['win_rate'],
            deviations=orient_report.deviations,
            strategy_adjustments=adjustments,
            evolved_strategies=evolved_list,
            memory_updates=memory_updates,
            next_day_focus="Optimize slippage and entry timing" if orient_report.actual_pnl < 0 else "Maintain current performance"
        )
