/**
 * AnalysisPanel —— 个股分析结果展示面板。
 *
 * 展示：
 * - 综合评分仪表盘（加权分 + 多空分布 + 置信度）
 * - 各 analyst 报告折叠面板（含 signals/metrics/key_factors）
 * - 辩论视图（bull/bear 左右分栏）
 * - 规则信号清单
 */
import { useMemo, useState, type FC } from 'react';
import { ChevronDown, ChevronRight, TrendingDown, TrendingUp, Minus } from 'lucide-react';
import type {
  AnalysisReportPayload,
  AnalysisSignal,
  AnalyzeResult,
  DebateResultPayload,
  SignalSummaryPayload,
} from '../services/api';
import { cn } from '../lib/utils';

interface AnalysisPanelProps {
  result: AnalyzeResult | null;
  loading?: boolean;
  error?: string;
}

const stanceColor = (stance?: string): string => {
  const s = String(stance || '').toLowerCase();
  if (s === 'bullish') return 'text-up-green';
  if (s === 'bearish') return 'text-down-red';
  return 'text-info-gray';
};

const stanceIcon = (stance?: string) => {
  const s = String(stance || '').toLowerCase();
  if (s === 'bullish') return <TrendingUp className="h-3 w-3" />;
  if (s === 'bearish') return <TrendingDown className="h-3 w-3" />;
  return <Minus className="h-3 w-3" />;
};

const directionBadge = (direction?: string): { label: string; cls: string } => {
  const d = String(direction || '').toUpperCase();
  if (d === 'BULL') return { label: '看多', cls: 'text-up-green border-up-green/40 bg-up-green/10' };
  if (d === 'BEAR') return { label: '看空', cls: 'text-down-red border-down-red/40 bg-down-red/10' };
  return { label: '中性', cls: 'text-info-gray border-border bg-bg-hover' };
};

const SignalRow: FC<{ signal: AnalysisSignal }> = ({ signal }) => {
  const badge = directionBadge(signal.direction);
  return (
    <div className="flex items-start gap-2 p-2 rounded bg-bg-primary/40 border border-border/40 text-[10px]">
      <span className={cn('px-1 py-0.5 rounded border font-bold shrink-0', badge.cls)}>{badge.label}</span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-mono font-bold text-neon-cyan/80">{signal.rule ?? '--'}</span>
          <span className="text-info-gray/60">强度 {signal.strength ?? '--'}</span>
          <span className="text-info-gray/40">[{signal.category ?? '--'}]</span>
        </div>
        <div className="text-info-gray/80 mt-0.5">{signal.description ?? '--'}</div>
      </div>
    </div>
  );
};

const ReportCard: FC<{ name: string; report: AnalysisReportPayload }> = ({ name, report }) => {
  const [expanded, setExpanded] = useState(false);
  const score = report.score ?? 50;
  const scoreColor = score > 55 ? 'text-up-green' : score < 45 ? 'text-down-red' : 'text-info-gray';
  const signals = report.signals ?? [];
  const metrics = report.metrics ?? {};

  return (
    <div className="rounded border border-border bg-bg-card/50 overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-2.5 hover:bg-bg-hover/30 transition-colors"
      >
        <div className="flex items-center gap-2">
          {expanded ? <ChevronDown className="h-3 w-3 text-info-gray/60" /> : <ChevronRight className="h-3 w-3 text-info-gray/60" />}
          <span className="text-[11px] font-bold uppercase tracking-wider text-white">{name}</span>
          <span className={cn('flex items-center gap-1 text-[10px] font-bold', stanceColor(report.stance))}>
            {stanceIcon(report.stance)}
            {report.stance || 'Neutral'}
          </span>
        </div>
        <div className="flex items-center gap-3 text-[10px] font-mono">
          {signals.length > 0 && <span className="text-info-gray/50">{signals.length} 信号</span>}
          <span className={cn('font-bold', scoreColor)}>{score.toFixed(1)}</span>
        </div>
      </button>
      {expanded && (
        <div className="px-2.5 pb-2.5 space-y-2 border-t border-border/50 pt-2">
          {report.summary && (
            <div className="text-[10px] text-info-gray/80 leading-relaxed">{report.summary}</div>
          )}
          {report.key_factors && report.key_factors.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {report.key_factors.map((f, i) => (
                <span key={i} className="px-1.5 py-0.5 rounded bg-bg-hover text-[9px] text-info-gray/70">{f}</span>
              ))}
            </div>
          )}
          {Object.keys(metrics).length > 0 && (
            <div className="text-[9px] text-info-gray/50 font-mono">
              {Object.entries(metrics).slice(0, 6).map(([k, v]) => (
                <span key={k} className="mr-3">{k}={String(v ?? '--').slice(0, 20)}</span>
              ))}
            </div>
          )}
          {signals.length > 0 && (
            <div className="space-y-1">
              <div className="text-[9px] text-info-gray/50 uppercase font-bold">规则信号</div>
              {signals.map((sig, i) => <SignalRow key={i} signal={sig} />)}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export const AnalysisPanel: FC<AnalysisPanelProps> = ({ result, loading, error }) => {
  const state = result?.state;
  const reports = state?.analysis_reports ?? {};
  const debate = state?.debate_results as DebateResultPayload | undefined;
  const signalSummary = state?.context?.signal_summary as SignalSummaryPayload | undefined;

  const allSignals = useMemo(() => signalSummary?.all_signals ?? [], [signalSummary]);

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center text-info-gray/60 text-xs">
        分析进行中...（规则引擎 + LLM 双轨运行）
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-full items-center justify-center text-down-red/80 text-xs p-4 text-center">
        {error}
      </div>
    );
  }

  if (!state) {
    return (
      <div className="flex h-full flex-col items-center justify-center text-info-gray/40 gap-2">
        <TrendingUp className="h-10 w-10 opacity-30" />
        <span className="text-xs">点击"开始分析"按钮触发 AI 多 agent 分析</span>
        <span className="text-[10px] text-info-gray/30">分析将运行：基本面 → 技术面 → 情绪 → 辩论 → 决策 → 风控</span>
      </div>
    );
  }

  const weightedScore = signalSummary?.weighted_score ?? signalSummary?.avg_score ?? 50;
  const bullCount = signalSummary?.bullish_count ?? 0;
  const bearCount = signalSummary?.bearish_count ?? 0;
  const conflict = signalSummary?.conflict;
  const confidence = signalSummary?.confidence ?? 0;

  return (
    <div className="flex h-full flex-col overflow-y-auto custom-scrollbar">
      {/* 综合评分仪表盘 */}
      <div className="p-3 border-b border-border bg-bg-card/30">
        <div className="grid grid-cols-4 gap-3">
          <div className="flex flex-col items-center justify-center p-2 rounded bg-bg-primary/40 border border-border">
            <span className="text-[9px] text-info-gray/50 uppercase font-mono">综合评分</span>
            <span className={cn(
              'text-2xl font-bold font-mono',
              weightedScore > 55 ? 'text-up-green' : weightedScore < 45 ? 'text-down-red' : 'text-info-gray'
            )}>
              {weightedScore.toFixed(1)}
            </span>
          </div>
          <div className="flex flex-col items-center justify-center p-2 rounded bg-bg-primary/40 border border-border">
            <span className="text-[9px] text-info-gray/50 uppercase font-mono">看多</span>
            <span className="text-2xl font-bold font-mono text-up-green">{bullCount}</span>
          </div>
          <div className="flex flex-col items-center justify-center p-2 rounded bg-bg-primary/40 border border-border">
            <span className="text-[9px] text-info-gray/50 uppercase font-mono">看空</span>
            <span className="text-2xl font-bold font-mono text-down-red">{bearCount}</span>
          </div>
          <div className="flex flex-col items-center justify-center p-2 rounded bg-bg-primary/40 border border-border">
            <span className="text-[9px] text-info-gray/50 uppercase font-mono">置信度</span>
            <span className={cn(
              'text-2xl font-bold font-mono',
              confidence > 60 ? 'text-up-green' : confidence > 30 ? 'text-warn-gold' : 'text-down-red'
            )}>
              {confidence.toFixed(0)}
            </span>
          </div>
        </div>
        {conflict && (
          <div className="mt-2 px-2 py-1 rounded bg-warn-gold/10 border border-warn-gold/30 text-[10px] text-warn-gold">
            ⚠ 多空信号冲突，建议谨慎
          </div>
        )}
      </div>

      {/* 决策结论 */}
      {state.trading_decision && (
        <div className="p-3 border-b border-border bg-bg-card/20">
          <div className="text-[9px] text-info-gray/50 uppercase font-bold mb-1">交易决策</div>
          <div className="flex items-center gap-3">
            <span className={cn(
              'px-2 py-1 rounded font-bold text-xs',
              state.decision === 'BUY' ? 'bg-up-green/20 text-up-green' :
              state.decision === 'SELL' ? 'bg-down-red/20 text-down-red' :
              'bg-bg-hover text-info-gray'
            )}>
              {state.decision || 'HOLD'}
            </span>
            {state.trading_decision.percentage ? (
              <span className="text-[10px] font-mono text-info-gray">仓位 {state.trading_decision.percentage}%</span>
            ) : null}
            {state.trading_decision.reason && (
              <span className="text-[10px] text-info-gray/70 flex-1">{state.trading_decision.reason}</span>
            )}
          </div>
        </div>
      )}

      {/* 辩论视图 */}
      {debate && (debate.bull_arguments?.length || debate.bear_arguments?.length) ? (
        <div className="p-3 border-b border-border">
          <div className="text-[9px] text-info-gray/50 uppercase font-bold mb-2">多空辩论</div>
          <div className="grid grid-cols-2 gap-2">
            <div className="p-2 rounded bg-up-green/5 border border-up-green/20">
              <div className="text-[9px] font-bold text-up-green uppercase mb-1 flex items-center gap-1">
                <TrendingUp className="h-3 w-3" /> 看多逻辑
              </div>
              <ul className="space-y-1">
                {(debate.bull_arguments ?? []).map((arg, i) => (
                  <li key={i} className="text-[10px] text-info-gray/80 leading-relaxed">• {arg}</li>
                ))}
              </ul>
            </div>
            <div className="p-2 rounded bg-down-red/5 border border-down-red/20">
              <div className="text-[9px] font-bold text-down-red uppercase mb-1 flex items-center gap-1">
                <TrendingDown className="h-3 w-3" /> 看空逻辑
              </div>
              <ul className="space-y-1">
                {(debate.bear_arguments ?? []).map((arg, i) => (
                  <li key={i} className="text-[10px] text-info-gray/80 leading-relaxed">• {arg}</li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      ) : null}

      {/* 各 analyst 报告 */}
      <div className="p-3 space-y-2">
        <div className="text-[9px] text-info-gray/50 uppercase font-bold">分析师报告</div>
        {Object.entries(reports).length === 0 ? (
          <div className="text-[10px] text-info-gray/40 italic p-2">无分析报告</div>
        ) : (
          Object.entries(reports).map(([key, report]) => (
            <ReportCard key={key} name={key} report={report} />
          ))
        )}
      </div>

      {/* 汇聚信号清单 */}
      {allSignals.length > 0 && (
        <div className="p-3 border-t border-border">
          <div className="text-[9px] text-info-gray/50 uppercase font-bold mb-2">
            全部规则信号 ({allSignals.length})
          </div>
          <div className="space-y-1">
            {allSignals.map((sig, i) => <SignalRow key={i} signal={sig} />)}
          </div>
        </div>
      )}
    </div>
  );
};

export default AnalysisPanel;
