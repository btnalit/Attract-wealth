import json
import logging
import math
import time
from typing import Any, Dict, List, Optional

from src.core.storage import get_ledger_db, get_main_db
from src.core.strategy_store import StrategyStore
from src.core.trading_ledger import TradingLedger

logger = logging.getLogger(__name__)

class QualityMonitor:
    """策略质量监控系统"""
    
    def __init__(self, strategy_store: Optional[StrategyStore] = None, ledger: Optional[TradingLedger] = None):
        self.strategy_store = strategy_store or StrategyStore()
        self.ledger = ledger or TradingLedger()
        self.initial_capital = 1_000_000.0  # 基准初始资金，用于回撤比例计算
    
    def calculate_metrics(self, trades: List[Dict[str, Any]]) -> Dict[str, float]:
        """从交易记录计算全部质量指标
        
        指标包括：
        - 胜率 (Win Rate)
        - 盈亏比 (Profit/Loss Ratio)
        - 最大回撤 (Max Drawdown)
        - 夏普比率 (Sharpe Ratio)
        - 卡尔玛比率 (Calmar Ratio)
        - Agent 响应耗时
        """
        if not trades:
            return {
                "win_rate": 0.0,
                "profit_loss_ratio": 0.0,
                "max_drawdown": 0.0,
                "sharpe_ratio": 0.0,
                "calmar_ratio": 0.0,
                "avg_response_time": 0.0,
                "trade_count": 0,
                "net_pnl": 0.0
            }

        pnls = [float(t.get("pnl", 0.0) or 0.0) for t in trades]
        trade_count = len(pnls)
        total_pnl = sum(pnls)
        
        # 1. 胜率 (Win Rate)
        wins = [p for p in pnls if p > 0]
        win_rate = len(wins) / trade_count if trade_count > 0 else 0.0
        
        # 2. 盈亏比 (Profit/Loss Ratio)
        losses = [abs(p) for p in pnls if p < 0]
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else (avg_win if avg_win > 0 else 0.0)

        # 3. 最大回撤 (Max Drawdown)
        cum_pnl = 0.0
        cum_pnls = []
        for p in pnls:
            cum_pnl += p
            cum_pnls.append(cum_pnl)
        
        peak = 0.0
        max_dd_abs = 0.0
        for val in cum_pnls:
            if val > peak:
                peak = val
            dd = peak - val
            if dd > max_dd_abs:
                max_dd_abs = dd
        
        # 归一化为比例 (基于初始资金 1,000,000)
        max_drawdown = max_dd_abs / self.initial_capital if self.initial_capital > 0 else 0.0

        # 4. 夏普比率 (Sharpe Ratio) - 基于单笔交易 PNL 的波动性
        mean_pnl = total_pnl / trade_count if trade_count > 0 else 0.0
        variance = sum((p - mean_pnl)**2 for p in pnls) / trade_count if trade_count > 0 else 0.0
        std_pnl = math.sqrt(variance)
        sharpe_ratio = mean_pnl / std_pnl if std_pnl > 0 else 0.0

        # 5. 卡尔玛比率 (Calmar Ratio)
        # 简单使用 (总收益率 / 最大回撤比例)
        total_return = total_pnl / self.initial_capital
        calmar_ratio = total_return / max_drawdown if max_drawdown > 0 else (total_return if total_return > 0 else 0.0)

        # 6. Agent 响应耗时 (Avg Response Time)
        latencies = [float(t.get("metadata", {}).get("response_time", 0.0) or 0.0) 
                     for t in trades if isinstance(t.get("metadata"), dict)]
        valid_latencies = [l for l in latencies if l > 0]
        avg_response_time = sum(valid_latencies) / len(valid_latencies) if valid_latencies else 0.0

        return {
            "win_rate": round(win_rate, 4),
            "profit_loss_ratio": round(profit_loss_ratio, 4),
            "max_drawdown": round(max_drawdown, 4),
            "sharpe_ratio": round(sharpe_ratio, 4),
            "calmar_ratio": round(calmar_ratio, 4),
            "avg_response_time": round(avg_response_time, 2),
            "trade_count": trade_count,
            "net_pnl": round(total_pnl, 2)
        }
    
    def evaluate_strategy(self, strategy_id: str) -> Dict[str, Any]:
        """评估单个策略的综合质量"""
        # 1. 获取该策略的所有交易记录 (假设 agent_id 与 strategy_id 关联)
        conn = get_main_db()
        try:
            cursor = conn.execute(
                "SELECT ticker, action, pnl, metadata FROM trading_records WHERE agent_id = ? AND status IN ('filled', 'partial')",
                (strategy_id,)
            )
            rows = cursor.fetchall()
        finally:
            conn.close()
        
        trades = []
        for r in rows:
            try:
                meta = json.loads(r[3]) if r[3] else {}
            except Exception:
                meta = {}
            trades.append({
                "ticker": r[0],
                "action": r[1],
                "pnl": r[2],
                "metadata": meta
            })
        
        # 2. 计算基础指标
        metrics = self.calculate_metrics(trades)
        
        # 如果交易记录中没有耗时，尝试从 ledger_entries 获取
        if metrics["avg_response_time"] == 0:
            metrics["avg_response_time"] = self._get_avg_latency_from_ledger(strategy_id)

        # 3. 计算综合评分 (Scoring Model)
        # 评分模型: 胜率 × 0.25 + 盈亏比 × 0.2 + (1 - 最大回撤) × 0.25 + 夏普比率归一化 × 0.2 + 响应速度 × 0.1
        
        wr = metrics["win_rate"]
        plr = metrics["profit_loss_ratio"]
        mdd = metrics["max_drawdown"]
        sr = metrics["sharpe_ratio"]
        latency = metrics["avg_response_time"]
        
        # 评分指标归一化
        norm_plr = min(plr / 3.0, 1.0)  # 盈亏比 3.0 为满分
        norm_sr = max(0.0, min(sr / 3.0, 1.0))  # 夏普比率 3.0 为满分
        # 响应速度：30s内 1.0分，300s以上 0分
        norm_speed = max(0.0, min(1.0, (300 - latency) / 270)) if latency > 0 else 0.5 

        score = (
            wr * 0.25 +
            norm_plr * 0.2 +
            (1.0 - mdd) * 0.25 +
            norm_sr * 0.2 +
            norm_speed * 0.1
        )
        score = round(score, 4)
        
        # 4. 更新 StrategyStore 中的指标
        store_metrics = {
            "win_rate": wr,
            "max_drawdown": mdd,
            "net_pnl": metrics["net_pnl"],
            "sharpe": sr,
            "trade_count": metrics["trade_count"],
            "avg_response_time": latency,
            "quality_score": score
        }
        self.strategy_store.update_strategy_metrics(strategy_id, store_metrics)
        
        # 触发 Gate 校验
        gate_result = self.strategy_store.evaluate_version_gate(strategy_id)
        passed_gate = gate_result.get("passed", False)
        
        # 5. 执行自动状态转换
        # 评分低于 0.4 标记为淘汰候选
        # 评分高于 0.8 标记为优质策略
        current_strategy = self.strategy_store.get_strategy(strategy_id)
        current_status = current_strategy.get("status", "active")
        
        new_status = current_status
        if score < 0.4 and current_status == "active":
            logger.info(f"Strategy {strategy_id} score {score} is below threshold 0.4, auto-retiring.")
            self.strategy_store.set_strategy_status(strategy_id, "retired")
            new_status = "retired"
        
        return {
            "strategy_id": strategy_id,
            "name": current_strategy.get("name"),
            "version": current_strategy.get("version"),
            "score": score,
            "metrics": metrics,
            "passed_gate": passed_gate,
            "gate_details": gate_result.get("checks", []),
            "old_status": current_status,
            "new_status": new_status,
            "recommendation": "PREMIUM" if score >= 0.8 else ("ELIMINATE" if score < 0.4 else "KEEP")
        }
    
    def get_eligible_strategies(self, min_score: float = 0.7) -> List[Dict[str, Any]]:
        """获取达到质量阈值的策略列表"""
        all_strategies = self.strategy_store.list_strategy_versions(status="active")
        eligible = []
        for s in all_strategies:
            try:
                eval_result = self.evaluate_strategy(s["id"])
                if eval_result["score"] >= min_score:
                    eligible.append(eval_result)
            except Exception as e:
                logger.error(f"Error evaluating strategy {s['id']}: {str(e)}")
        return eligible
    
    def get_eliminated_strategies(self) -> List[Dict[str, Any]]:
        """获取应被淘汰的策略列表"""
        # 只检查目前仍为 active 的策略
        active_strategies = self.strategy_store.list_strategy_versions(status="active")
        eliminated = []
        for s in active_strategies:
            try:
                eval_result = self.evaluate_strategy(s["id"])
                if eval_result["score"] < 0.4:
                    eliminated.append(eval_result)
            except Exception as e:
                logger.error(f"Error evaluating strategy {s['id']}: {str(e)}")
        return eliminated
    
    def update_quality_scores(self) -> Dict[str, float]:
        """批量更新所有活跃策略的质量评分"""
        active_strategies = self.strategy_store.list_strategy_versions(status="active")
        results = {}
        for s in active_strategies:
            try:
                eval_result = self.evaluate_strategy(s["id"])
                results[s["id"]] = eval_result["score"]
            except Exception as e:
                logger.error(f"Failed to update quality score for {s['id']}: {str(e)}")
        return results
    
    def generate_report(self) -> str:
        """生成可读的质量监控报告"""
        # 注意：list_strategy_versions 返回的是列表，可能需要分页
        active_strategies = self.strategy_store.list_strategy_versions(status="active", limit=100)
        retired_strategies = self.strategy_store.list_strategy_versions(status="retired", limit=100)
        
        report = []
        report.append("=== 🐉 来财 (Attract-wealth) 策略质量监控报告 ===")
        report.append(f"报告生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        report.append(f"活跃策略总数: {len(active_strategies)}")
        report.append(f"已退役策略数: {len(retired_strategies)}")
        report.append("=" * 50)
        
        if not active_strategies:
            report.append("\n[!] 目前没有活跃策略。")
        else:
            report.append("\n[活跃策略表现概览]")
            for s in active_strategies:
                try:
                    res = self.evaluate_strategy(s["id"])
                    report.append(f"策略: {res['name']} (v{res['version']})")
                    report.append(f"  - 综合评分: {res['score']} [{res['recommendation']}]")
                    report.append(f"  - 胜率: {res['metrics']['win_rate']:.2%}")
                    report.append(f"  - 盈亏比: {res['metrics']['profit_loss_ratio']:.2f}")
                    report.append(f"  - 夏普比率: {res['metrics']['sharpe_ratio']:.2f}")
                    report.append(f"  - 最大回撤: {res['metrics']['max_drawdown']:.2%}")
                    report.append(f"  - 平均耗时: {res['metrics']['avg_response_time']:.2f}s")
                    report.append(f"  - 累计成交: {res['metrics']['trade_count']}")
                    report.append("-" * 30)
                except Exception as e:
                    report.append(f"策略: {s['name']} (ID: {s['id']}) - 评估失败: {str(e)}")
            
        return "\n".join(report)

    def _get_avg_latency_from_ledger(self, agent_id: str) -> float:
        """从审计日志 (ledger_entries) 中提取并计算 Agent 平均响应耗时"""
        conn = get_ledger_db()
        try:
            # 获取该 Agent 的所有分析开始和结束记录
            cursor = conn.execute(
                """
                SELECT metadata, timestamp, action FROM ledger_entries 
                WHERE agent_id = ? AND action IN ('GRAPH_START', 'GRAPH_END')
                ORDER BY timestamp ASC
                """,
                (agent_id,)
            )
            rows = cursor.fetchall()
        finally:
            conn.close()
            
        durations = []
        starts = {} 
        for meta_json, ts, action in rows:
            try:
                meta = json.loads(meta_json or "{}")
            except Exception:
                continue
            session_id = meta.get("session_id")
            if not session_id:
                continue
            if action == 'GRAPH_START':
                starts[session_id] = ts
            elif action == 'GRAPH_END' and session_id in starts:
                durations.append(ts - starts[session_id])
                del starts[session_id]
        
        return round(sum(durations) / len(durations), 2) if durations else 0.0
