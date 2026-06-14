/**
 * StockDiagnose —— 个股诊断页 /diagnose/:ticker
 *
 * 一页看全某股票的所有分析维度：
 * - K 线图（KLineChart 蜡烛图）
 * - 综合评分 + 决策结论
 * - 技术指标卡片
 * - 分析师报告（AnalysisPanel）
 * - 资金面（FundPanel）
 * - 风险提示（ST/涨停/T+1）
 */
import { useCallback, useEffect, useMemo, useState, type FC } from 'react';
import { useParams } from 'react-router-dom';
import { AlertTriangle, Activity, Loader2, Search } from 'lucide-react';
import { monitorApi, tradingApi, type AnalyzeResult } from '../services/api';
import { KLineChart, type KLineDataPoint } from '../components/KLineChart';
import { AnalysisPanel } from '../components/AnalysisPanel';
import { FundPanel } from '../components/FundPanel';
import { cn } from '../lib/utils';

interface KlineRaw {
  ts?: number;
  date?: string;
  open?: number;
  high?: number;
  low?: number;
  close?: number;
  volume?: number;
}

const toNum = (v: unknown): number | null => {
  const n = typeof v === 'number' ? v : Number(v);
  return Number.isFinite(n) ? n : null;
};

const StockDiagnose: FC = () => {
  const { ticker } = useParams<{ ticker: string }>();
  const [inputTicker, setInputTicker] = useState(ticker || '000001');
  const [activeTicker, setActiveTicker] = useState(ticker || '000001');

  const [kline, setKline] = useState<KlineRaw[]>([]);
  const [analyzeResult, setAnalyzeResult] = useState<AnalyzeResult | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeError, setAnalyzeError] = useState('');
  const [loadingKline, setLoadingKline] = useState(false);

  const handleAnalyze = useCallback(async (sym: string) => {
    setAnalyzing(true);
    setAnalyzeError('');
    try {
      const result = await tradingApi.analyze<AnalyzeResult>(sym);
      setAnalyzeResult(result);
    } catch (err) {
      setAnalyzeError(err instanceof Error ? err.message : String(err));
    } finally {
      setAnalyzing(false);
    }
  }, []);

  const fetchKline = useCallback(async (sym: string) => {
    setLoadingKline(true);
    try {
      const payload = await monitorApi.getKline<KlineRaw[] | { data?: KlineRaw[] }>(sym, 120);
      const raw = Array.isArray(payload) ? payload : (payload?.data ?? []);
      setKline(Array.isArray(raw) ? raw : []);
    } catch {
      setKline([]);
    } finally {
      setLoadingKline(false);
    }
  }, []);

  useEffect(() => {
    void fetchKline(activeTicker);
    void handleAnalyze(activeTicker);
  }, [activeTicker, fetchKline, handleAnalyze]);

  const klineChartData: KLineDataPoint[] = useMemo(
    () => kline.map((k) => ({
      date: k.date ?? new Date((k.ts ?? 0) * 1000).toISOString().slice(0, 10),
      open: toNum(k.open) ?? 0,
      high: toNum(k.high) ?? 0,
      low: toNum(k.low) ?? 0,
      close: toNum(k.close) ?? 0,
      volume: toNum(k.volume) ?? 0,
    })),
    [kline],
  );

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputTicker.trim()) return;
    setActiveTicker(inputTicker.trim());
  };

  // 从 analyze 结果提取技术指标 + 风险标记
  const techIndicators = analyzeResult?.state?.context?.technical_indicators as Record<string, unknown> | undefined;
  const ashareFlags = analyzeResult?.state?.context?.ashare_flags as Record<string, unknown> | undefined;
  const flags = (ashareFlags?.flags ?? []) as string[];
  const riskFlags = Array.isArray(flags) ? flags : [];

  const signalSummary = analyzeResult?.state?.context?.signal_summary as Record<string, unknown> | undefined;

  return (
    <div className="flex h-full flex-col overflow-hidden bg-bg-primary text-gray-300 font-mono">
      {/* 顶部 ticker 输入 */}
      <div className="flex items-center justify-between border-b border-border bg-bg-card/50 p-2 px-4">
        <form onSubmit={handleSubmit} className="flex items-center gap-3">
          <Search className="h-3.5 w-3.5 text-info-gray/60" />
          <input
            type="text"
            value={inputTicker}
            onChange={(e) => setInputTicker(e.target.value)}
            placeholder="股票代码"
            className="w-32 bg-transparent text-xs text-white outline-none placeholder:text-info-gray/40 uppercase"
          />
          <span className="text-[10px] text-info-gray/50">诊断目标：{activeTicker.toUpperCase()}</span>
        </form>
        <div className="flex items-center gap-2">
          {analyzing && <Loader2 className="h-3.5 w-3.5 animate-spin text-neon-cyan" />}
          <span className="text-[10px] text-info-gray/50">{analyzing ? '分析中...' : '分析就绪'}</span>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* 左侧：K线 + 指标卡片 */}
        <div className="flex flex-[3] flex-col border-r border-border overflow-y-auto">
          {/* 风险提示横幅 */}
          {riskFlags.length > 0 && (
            <div className="flex items-center gap-2 px-4 py-2 bg-warn-gold/10 border-b border-warn-gold/30 text-[10px] text-warn-gold">
              <AlertTriangle className="h-3.5 w-3.5" />
              <span>风险标记：{riskFlags.join(' / ')}</span>
            </div>
          )}

          {/* K 线图 */}
          <div className="p-4">
            <div className="text-[10px] text-info-gray/50 uppercase font-bold mb-2">K 线图</div>
            {loadingKline ? (
              <div className="flex items-center justify-center h-[300px] text-info-gray/50 text-xs">
                <Loader2 className="h-4 w-4 animate-spin mr-2" /> 加载 K 线...
              </div>
            ) : klineChartData.length >= 2 ? (
              <KLineChart data={klineChartData} height={300} />
            ) : (
              <div className="flex items-center justify-center h-[300px] text-info-gray/40 text-xs">暂无 K 线数据</div>
            )}
          </div>

          {/* 技术指标卡片网格 */}
          {techIndicators && Object.keys(techIndicators).length > 0 && (
            <div className="p-4 border-t border-border">
              <div className="text-[10px] text-info-gray/50 uppercase font-bold mb-2">技术指标</div>
              <div className="grid grid-cols-4 gap-2">
                {(['MA5', 'MA10', 'MA20', 'MA60', 'RSI_14', 'MACD_DIF', 'MACD_HIST', 'MACD_SIGNAL'] as const).map((key) => {
                  const val = toNum(techIndicators[key]);
                  return (
                    <div key={key} className="p-2 rounded bg-bg-card/50 border border-border">
                      <div className="text-[9px] text-info-gray/50 uppercase">{key}</div>
                      <div className={cn('text-sm font-bold', val === null ? 'text-info-gray/40' : 'text-white')}>
                        {val === null ? '--' : val.toFixed(2)}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* 综合评分 + 决策 */}
          {signalSummary && (
            <div className="p-4 border-t border-border">
              <div className="text-[10px] text-info-gray/50 uppercase font-bold mb-2">综合评估</div>
              <div className="grid grid-cols-4 gap-2">
                <ScoreCard label="加权评分" value={toNum(signalSummary.weighted_score ?? signalSummary.avg_score)} />
                <ScoreCard label="看多" value={toNum(signalSummary.bullish_count)} color="green" />
                <ScoreCard label="看空" value={toNum(signalSummary.bearish_count)} color="red" />
                <ScoreCard label="置信度" value={toNum(signalSummary.confidence)} suffix="%" />
              </div>
              {analyzeResult?.state?.trading_decision && (
                <div className="mt-2 p-2 rounded bg-bg-card/50 border border-border text-[10px]">
                  <span className="text-info-gray/50">决策：</span>
                  <span className={cn(
                    'font-bold ml-1',
                    String(analyzeResult.state.decision).toUpperCase() === 'BUY' ? 'text-up-green' :
                    String(analyzeResult.state.decision).toUpperCase() === 'SELL' ? 'text-down-red' : 'text-info-gray'
                  )}>
                    {analyzeResult.state.decision}
                  </span>
                  {analyzeResult.state.trading_decision.reason && (
                    <span className="text-info-gray/70 ml-2">{String(analyzeResult.state.trading_decision.reason)}</span>
                  )}
                </div>
              )}
            </div>
          )}

          {/* 资金面 */}
          <div className="p-4 border-t border-border">
            <div className="text-[10px] text-info-gray/50 uppercase font-bold mb-2">资金面</div>
            <FundPanel analyzeResult={analyzeResult} />
          </div>
        </div>

        {/* 右侧：完整分析报告 */}
        <div className="flex flex-1 flex-col overflow-hidden bg-bg-card/20">
          <div className="px-4 py-2 border-b border-border bg-bg-card/50">
            <div className="flex items-center gap-2 text-neon-cyan">
              <Activity className="h-3 w-3" />
              <span className="text-[10px] font-bold uppercase tracking-widest">AI 分析报告</span>
            </div>
          </div>
          <div className="flex-1 overflow-hidden">
            <AnalysisPanel result={analyzeResult} loading={analyzing} error={analyzeError} />
          </div>
        </div>
      </div>
    </div>
  );
};

const ScoreCard: FC<{ label: string; value: number | null; color?: 'green' | 'red'; suffix?: string }> = ({ label, value, color, suffix }) => (
  <div className="p-2 rounded bg-bg-card/50 border border-border">
    <div className="text-[9px] text-info-gray/50 uppercase">{label}</div>
    <div className={cn(
      'text-lg font-bold',
      value === null ? 'text-info-gray/40' :
      color === 'green' ? 'text-up-green' :
      color === 'red' ? 'text-down-red' : 'text-white'
    )}>
      {value === null ? '--' : `${value.toFixed(value > 100 ? 0 : (suffix ? 0 : 1))}${suffix || ''}`}
    </div>
  </div>
);

export default StockDiagnose;
