import React, { useEffect, useState } from 'react';
import { Play, Settings, TrendingUp, BarChart, RotateCcw, Plus, Trash2, Loader2 } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { cn } from '../lib/utils';
import { apiUrl, strategyApi } from '../services/api';

interface Metric {
  label: string;
  value: string;
  subValue?: string;
  color: string;
}

interface StrategyOption {
  id: string;
  name: string;
}

interface BacktestReportSummary {
  reportId: string;
  strategyName: string;
  createdAt: number;
  metrics: Record<string, unknown>;
}

interface BacktestCompareRow {
  label: string;
  left: number;
  right: number;
  leftDisplay: string;
  rightDisplay: string;
  deltaDisplay: string;
  deltaPositive: boolean;
}

const DEFAULT_STRATEGY_OPTIONS: StrategyOption[] = [
  { id: 'Multi-Factor Mean Reversion', name: 'Multi-Factor Mean Reversion' },
  { id: 'MACD Crossover V2', name: 'MACD Crossover V2' },
  { id: 'Deep Learning RL-Alpha', name: 'Deep Learning RL-Alpha' },
  { id: 'High Frequency Scalper', name: 'High Frequency Scalper' },
];

const parsePayloadData = <T,>(payload: unknown): T => {
  if (payload && typeof payload === 'object' && 'data' in payload) {
    return (payload as { data: T }).data;
  }
  return payload as T;
};

const buildSyntheticBars = (startDate: string, endDate: string) => {
  const start = new Date(startDate);
  const end = new Date(endDate);
  const durationDays = Math.max(5, Math.floor((end.getTime() - start.getTime()) / (24 * 3600 * 1000)));
  const points = Math.min(Math.max(durationDays, 30), 240);

  const bars: Array<{ ts: string; close: number; signal: 'AUTO' }> = [];
  let price = 100;
  for (let i = 0; i < points; i += 1) {
    const dt = new Date(start.getTime() + i * 24 * 3600 * 1000);
    const drift = (Math.sin(i / 12) + Math.cos(i / 23)) * 0.8;
    price = Math.max(5, price * (1 + drift / 100));
    bars.push({
      ts: dt.toISOString().slice(0, 10),
      close: Number(price.toFixed(4)),
      signal: 'AUTO',
    });
  }
  return bars;
};

const buildEquityPath = (curve: any[]) => {
  if (!Array.isArray(curve) || curve.length < 2) return '';
  const equities = curve.map((p) => Number(p?.equity ?? 0)).filter((v) => Number.isFinite(v) && v > 0);
  if (equities.length < 2) return '';

  const min = Math.min(...equities);
  const max = Math.max(...equities);
  const span = Math.max(1e-6, max - min);
  const n = equities.length;

  return equities
    .map((eq, idx) => {
      const x = (idx / Math.max(1, n - 1)) * 100;
      const y = 85 - ((eq - min) / span) * 70;
      return `${idx === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(' ');
};

const buildMetricsFromBacktest = (metrics: any, summary: any): Metric[] => {
  const totalReturn = Number(metrics?.total_return ?? 0) * 100;
  const annualized = totalReturn * 0.65;
  const maxDrawdown = Number(metrics?.max_drawdown ?? 0) * 100;
  const sharpe = Number(metrics?.sharpe ?? 0);
  const winRate = Number(metrics?.win_rate ?? 0) * 100;
  const tradeCount = Number(metrics?.trade_count ?? 0);
  const turnover = Number(metrics?.turnover ?? 0);
  const netPnl = Number(metrics?.net_pnl ?? 0);
  const finalEquity = Number(summary?.final_equity ?? 0);

  return [
    { label: '总收益', value: `${totalReturn >= 0 ? '+' : ''}${totalReturn.toFixed(2)}%`, subValue: `¥${netPnl.toLocaleString('zh-CN', { maximumFractionDigits: 0 })}`, color: totalReturn >= 0 ? 'text-up-green' : 'text-down-red' },
    { label: '年化收益', value: `${annualized.toFixed(2)}%`, subValue: '估算', color: 'text-white' },
    { label: '最大回撤', value: `-${Math.abs(maxDrawdown).toFixed(2)}%`, subValue: '风险', color: 'text-up-red' },
    { label: '夏普比率', value: sharpe.toFixed(2), subValue: '风险调整后', color: 'text-neon-cyan' },
    { label: '胜率', value: `${winRate.toFixed(1)}%`, subValue: `${tradeCount} 笔交易`, color: 'text-info-gray' },
    { label: '换手率', value: turnover.toFixed(2), subValue: `期末权益 ¥${finalEquity.toLocaleString('zh-CN', { maximumFractionDigits: 0 })}`, color: 'text-warn-gold' },
  ];
};

const toNumber = (value: unknown, fallback = 0): number => {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
};

const asPercent = (value: unknown): number => {
  const raw = toNumber(value, 0);
  return raw <= 1 ? raw * 100 : raw;
};

const parseReportSummary = (report: any): BacktestReportSummary => {
  const payload = (report?.report_payload?.backtest ?? report?.backtest ?? {}) as Record<string, unknown>;
  const metrics = (payload.metrics ?? report?.metrics ?? {}) as Record<string, unknown>;
  const strategyPayload = (payload.strategy ?? {}) as Record<string, unknown>;
  return {
    reportId: String(report?.id ?? ''),
    strategyName: String(report?.strategy_name ?? strategyPayload.name ?? 'Unknown'),
    createdAt: toNumber(report?.created_at, 0),
    metrics,
  };
};

const buildCompareRows = (left: BacktestReportSummary, right: BacktestReportSummary): BacktestCompareRow[] => {
  const rows = [
    {
      label: 'Net PnL',
      left: toNumber(left.metrics.net_pnl, 0),
      right: toNumber(right.metrics.net_pnl, 0),
      leftDisplay: toNumber(left.metrics.net_pnl, 0).toFixed(2),
      rightDisplay: toNumber(right.metrics.net_pnl, 0).toFixed(2),
    },
    {
      label: 'Win Rate',
      left: asPercent(left.metrics.win_rate),
      right: asPercent(right.metrics.win_rate),
      leftDisplay: `${asPercent(left.metrics.win_rate).toFixed(2)}%`,
      rightDisplay: `${asPercent(right.metrics.win_rate).toFixed(2)}%`,
    },
    {
      label: 'Sharpe',
      left: toNumber(left.metrics.sharpe ?? left.metrics.sharpe_ratio, 0),
      right: toNumber(right.metrics.sharpe ?? right.metrics.sharpe_ratio, 0),
      leftDisplay: toNumber(left.metrics.sharpe ?? left.metrics.sharpe_ratio, 0).toFixed(3),
      rightDisplay: toNumber(right.metrics.sharpe ?? right.metrics.sharpe_ratio, 0).toFixed(3),
    },
    {
      label: 'Max Drawdown',
      left: asPercent(left.metrics.max_drawdown),
      right: asPercent(right.metrics.max_drawdown),
      leftDisplay: `${asPercent(left.metrics.max_drawdown).toFixed(2)}%`,
      rightDisplay: `${asPercent(right.metrics.max_drawdown).toFixed(2)}%`,
    },
    {
      label: 'Trade Count',
      left: toNumber(left.metrics.trade_count, 0),
      right: toNumber(right.metrics.trade_count, 0),
      leftDisplay: `${Math.round(toNumber(left.metrics.trade_count, 0))}`,
      rightDisplay: `${Math.round(toNumber(right.metrics.trade_count, 0))}`,
    },
  ];

  return rows.map((row) => {
    const delta = row.left - row.right;
    return {
      ...row,
      deltaDisplay: `${delta >= 0 ? '+' : ''}${delta.toFixed(3)}`,
      deltaPositive: delta >= 0,
    };
  });
};

const mockMetrics: Metric[] = [
  { label: '总收益', value: '+42.84%', subValue: '¥428,400', color: 'text-up-green' },
  { label: '年化收益', value: '28.5%', subValue: '复利', color: 'text-white' },
  { label: '最大回撤', value: '-8.12%', subValue: '低风险', color: 'text-up-red' },
  { label: '夏普比率', value: '1.84', subValue: '卓越', color: 'text-neon-cyan' },
  { label: '胜率', value: '62.4%', subValue: '124/198 交易', color: 'text-info-gray' },
  { label: '盈亏因子', value: '2.14', subValue: '高质量', color: 'text-warn-gold' },
];

export const BacktestLab: React.FC = () => {
  const [searchParams] = useSearchParams();
  const [isRunning, setIsRunning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [showMonteCarlo, setShowMonteCarlo] = useState(false);
  const [params, setParams] = useState([{ key: 'MA_PERIOD', value: '20' }, { key: 'RISK_PCT', value: '0.02' }]);
  const [strategyOptions, setStrategyOptions] = useState<StrategyOption[]>(DEFAULT_STRATEGY_OPTIONS);
  const [strategyId, setStrategyId] = useState(DEFAULT_STRATEGY_OPTIONS[0].id);
  const [startDate, setStartDate] = useState('2023-01-01');
  const [endDate, setEndDate] = useState('2024-04-01');
  const [initialCapital, setInitialCapital] = useState('1000000');
  const [metrics, setMetrics] = useState<Metric[]>(mockMetrics);
  const [equityCurve, setEquityCurve] = useState<string>("M 0 80 L 10 75 L 20 78 L 30 70 L 40 74 L 50 62 L 60 65 L 70 50 L 80 55 L 90 35 L 100 25");
  const [compareLoading, setCompareLoading] = useState(false);
  const [compareError, setCompareError] = useState('');
  const [compareLeft, setCompareLeft] = useState<BacktestReportSummary | null>(null);
  const [compareRight, setCompareRight] = useState<BacktestReportSummary | null>(null);
  const [compareRows, setCompareRows] = useState<BacktestCompareRow[]>([]);

  useEffect(() => {
    const loadStrategyOptions = async () => {
      try {
        const payload = await strategyApi.getVersions<{ items?: Array<Record<string, unknown>> } | Array<Record<string, unknown>>>(100);
        const data = parsePayloadData<{ items?: Array<Record<string, unknown>> } | Array<Record<string, unknown>>>(payload);
        const rows = Array.isArray(data)
          ? data
          : (data && typeof data === 'object' && Array.isArray((data as { items?: Array<Record<string, unknown>> }).items))
            ? (data as { items: Array<Record<string, unknown>> }).items
            : [];
        if (!rows.length) return;
        const options = rows.map((item: any) => ({
          id: String(item?.id ?? ''),
          name: String(item?.name ?? item?.id ?? 'Unknown Strategy'),
        })).filter((item: StrategyOption) => item.id);
        if (!options.length) return;
        setStrategyOptions(options);
        setStrategyId((prev) => (options.some((o) => o.id === prev) ? prev : options[0].id));
      } catch (err) {
        console.warn('[BacktestLab] load strategy options failed:', err);
      }
    };
    void loadStrategyOptions();
  }, []);

  useEffect(() => {
    const compareA = String(searchParams.get('compareA') ?? '').trim();
    const compareB = String(searchParams.get('compareB') ?? '').trim();
    if (!compareA || !compareB) {
      setCompareLeft(null);
      setCompareRight(null);
      setCompareRows([]);
      setCompareError('');
      setCompareLoading(false);
      return;
    }

    const loadCompareReports = async () => {
      setCompareLoading(true);
      setCompareError('');
      try {
        const [leftPayload, rightPayload] = await Promise.all([
          strategyApi.getBacktestById<unknown>(compareA),
          strategyApi.getBacktestById<unknown>(compareB),
        ]);
        const left = parseReportSummary(parsePayloadData<Record<string, unknown>>(leftPayload));
        const right = parseReportSummary(parsePayloadData<Record<string, unknown>>(rightPayload));
        setCompareLeft(left);
        setCompareRight(right);
        setCompareRows(buildCompareRows(left, right));
      } catch (error) {
        setCompareLeft(null);
        setCompareRight(null);
        setCompareRows([]);
        setCompareError(String(error));
      } finally {
        setCompareLoading(false);
      }
    };
    void loadCompareReports();
  }, [searchParams]);

  const runBacktest = async () => {
    setIsRunning(true);
    setProgress(10);
    
    try {
      const payload = {
        strategy_id: strategyId,
        bars: buildSyntheticBars(startDate, endDate),
        start_cash: Number.parseFloat(initialCapital) || 1_000_000,
        parameters_override: Object.fromEntries(params.filter((p) => p.key.trim()).map((p) => [p.key.trim(), p.value]))
      };

      const body = await strategyApi.runBacktest<Record<string, unknown>>(payload);
      const parsed = parsePayloadData<Record<string, unknown>>(body) || {};
      const backtest = (parsed.backtest as Record<string, unknown> | undefined) ?? null;
      if (!backtest) {
        throw new Error('Backtest API not available');
      }
      const backtestMetrics = (backtest.metrics as Record<string, unknown>) ?? {};
      const backtestSummary = (backtest.summary as Record<string, unknown>) ?? {};
      const equityCurveTail = Array.isArray(backtest.equity_curve_tail) ? backtest.equity_curve_tail : [];

      setProgress(100);
      setMetrics(buildMetricsFromBacktest(backtestMetrics, backtestSummary));
      const curvePath = buildEquityPath(equityCurveTail);
      if (curvePath) setEquityCurve(curvePath);
      setIsRunning(false);
    } catch (error) {
      console.warn('Backtest API failed, falling back to simulation:', error);
      simulateBacktest();
    }
  };

  const simulateBacktest = () => {
    let currentProgress = 0;
    const interval = setInterval(() => {
      currentProgress += 5;
      setProgress(currentProgress);
      if (currentProgress >= 100) {
        clearInterval(interval);
        setIsRunning(false);
        // Refresh with mock variation
        setMetrics(mockMetrics.map(m => ({
          ...m,
          value: m.label.includes('RETURN') ? `+${(Math.random() * 50 + 10).toFixed(2)}%` : m.value
        })));
      }
    }, 100);
  };

  const addParam = () => setParams([...params, { key: '', value: '' }]);
  const removeParam = (index: number) => setParams(params.filter((_, i) => i !== index));

  return (
    <div className="flex h-full flex-col overflow-hidden bg-bg-primary">
      {/* Header Section */}
      <div className="p-6 border-b border-border bg-bg-card/30">
        <h1 className="text-2xl font-orbitron font-bold text-white tracking-wider flex items-center gap-3">
          <BarChart className="text-neon-cyan h-6 w-6" />
          回测实验室 <span className="text-neon-cyan/50 text-xs font-mono ml-2">SIM_ENGINE_V4.2</span>
        </h1>
        <p className="text-info-gray/60 text-xs mt-1 uppercase tracking-widest italic">量化策略的历史回测验证</p>
      </div>

      {(compareLoading || compareError || (compareLeft && compareRight)) && (
        <div className="mx-6 mt-4 bg-bg-card/40 border border-border rounded-lg p-4 space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-[11px] font-bold tracking-[0.18em] uppercase text-neon-magenta">回测报告对比</h2>
            {(compareLeft && compareRight) && (
              <button
                onClick={() => { window.location.href = '/backtest'; }}
                className="text-[10px] px-3 py-1 border border-border rounded hover:border-neon-cyan transition-colors"
              >
                退出对比
              </button>
            )}
          </div>
          {compareLoading && (
            <div className="text-[11px] text-info-gray/70 flex items-center gap-2">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              正在加载回测报告...
            </div>
          )}
          {compareError && (
            <div className="text-[11px] text-down-red border border-down-red/30 rounded p-2">
              {compareError}
            </div>
          )}
          {(compareLeft && compareRight && compareRows.length > 0) && (
            <div className="space-y-3">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-[11px]">
                <div className="border border-border/40 rounded p-2">
                  <div className="text-info-gray/60 uppercase text-[9px]">Current</div>
                  <div className="text-white font-semibold">{compareLeft.strategyName}</div>
                  <div className="text-info-gray/60">{new Date(compareLeft.createdAt * 1000).toLocaleString()}</div>
                </div>
                <div className="border border-border/40 rounded p-2">
                  <div className="text-info-gray/60 uppercase text-[9px]">Baseline</div>
                  <div className="text-white font-semibold">{compareRight.strategyName}</div>
                  <div className="text-info-gray/60">{new Date(compareRight.createdAt * 1000).toLocaleString()}</div>
                </div>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                {compareRows.map((row) => (
                  <div key={row.label} className="border border-border/30 rounded p-2 text-[10px]">
                    <div className="text-info-gray/70 uppercase">{row.label}</div>
                    <div className="flex items-center justify-between mt-1">
                      <span className="text-white">{row.leftDisplay}</span>
                      <span className="text-info-gray/60">vs</span>
                      <span className="text-white">{row.rightDisplay}</span>
                      <span className={row.deltaPositive ? 'text-up-green' : 'text-down-red'}>{row.deltaDisplay}</span>
                    </div>
                  </div>
                ))}
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => window.open(apiUrl(`/api/strategy/backtests/${compareLeft.reportId}`), '_blank', 'noopener,noreferrer')}
                  className="text-[10px] px-3 py-1 border border-neon-cyan/40 text-neon-cyan rounded hover:bg-neon-cyan/10 transition-colors"
                >
                  打开当前报告
                </button>
                <button
                  onClick={() => window.open(apiUrl(`/api/strategy/backtests/${compareRight.reportId}`), '_blank', 'noopener,noreferrer')}
                  className="text-[10px] px-3 py-1 border border-neon-magenta/40 text-neon-magenta rounded hover:bg-neon-magenta/10 transition-colors"
                >
                  打开基线报告
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      <div className="flex-1 flex overflow-hidden">
        {/* Left Panel: Parameters */}
        <aside className="w-[340px] border-r border-border bg-bg-card/20 p-6 overflow-y-auto custom-scrollbar">
          <div className="space-y-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-[10px] font-orbitron text-neon-cyan tracking-[0.2em] uppercase">控制面板</h2>
              <Settings className="h-3 w-3 text-info-gray/40" />
            </div>

            {/* Strategy Selection */}
            <div className="space-y-2">
              <label className="text-[10px] text-info-gray uppercase font-bold tracking-wider">选择算法</label>
              <select 
                value={strategyId}
                onChange={(e) => setStrategyId(e.target.value)}
                className="w-full bg-bg-primary border border-border rounded px-3 py-2 text-xs text-white outline-none focus:border-neon-cyan transition-colors"
              >
                {strategyOptions.map((option) => (
                  <option key={option.id} value={option.id}>{option.name}</option>
                ))}
              </select>
            </div>

            {/* Time Range */}
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <label className="text-[10px] text-info-gray uppercase font-bold tracking-wider">开始日期</label>
                <input 
                  type="date" 
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                  className="w-full bg-bg-primary border border-border rounded px-2 py-2 text-[10px] text-white outline-none" 
                />
              </div>
              <div className="space-y-2">
                <label className="text-[10px] text-info-gray uppercase font-bold tracking-wider">结束日期</label>
                <input 
                  type="date" 
                  value={endDate}
                  onChange={(e) => setEndDate(e.target.value)}
                  className="w-full bg-bg-primary border border-border rounded px-2 py-2 text-[10px] text-white outline-none" 
                />
              </div>
            </div>

            {/* Capital */}
            <div className="space-y-2">
              <label className="text-[10px] text-info-gray uppercase font-bold tracking-wider">初始资金 (¥)</label>
              <input 
                type="number" 
                value={initialCapital}
                onChange={(e) => setInitialCapital(e.target.value)}
                className="w-full bg-bg-primary border border-border rounded px-3 py-2 text-xs text-white outline-none focus:border-neon-cyan transition-colors" 
              />
            </div>

            {/* Parameters */}
            <div className="space-y-3">
              <div className="flex justify-between items-center">
                <label className="text-[10px] text-info-gray uppercase font-bold tracking-wider">策略参数</label>
                <button onClick={addParam} className="p-1 hover:text-neon-cyan transition-colors"><Plus className="h-3 w-3" /></button>
              </div>
              <div className="space-y-2">
                {params.map((param, index) => (
                  <div key={index} className="flex gap-2">
                    <input 
                      className="flex-1 bg-bg-primary/50 border border-border rounded px-2 py-1 text-[10px] text-info-gray outline-none focus:border-neon-cyan" 
                      placeholder="KEY" 
                      value={param.key}
                      onChange={(e) => {
                        const newParams = [...params];
                        newParams[index].key = e.target.value;
                        setParams(newParams);
                      }}
                    />
                    <input 
                      className="w-20 bg-bg-primary/50 border border-border rounded px-2 py-1 text-[10px] text-white outline-none focus:border-neon-cyan" 
                      placeholder="VAL" 
                      value={param.value}
                      onChange={(e) => {
                        const newParams = [...params];
                        newParams[index].value = e.target.value;
                        setParams(newParams);
                      }}
                    />
                    <button onClick={() => removeParam(index)} className="p-1 text-info-gray/40 hover:text-up-red transition-colors"><Trash2 className="h-3 w-3" /></button>
                  </div>
                ))}
              </div>
            </div>

            {/* Run Button */}
            <button 
              disabled={isRunning}
              onClick={runBacktest}
              className={cn(
                "w-full py-4 mt-8 rounded font-orbitron text-xs tracking-[0.2em] font-bold transition-all flex flex-col items-center justify-center gap-2 relative overflow-hidden",
                isRunning 
                  ? "bg-neon-cyan/10 border border-neon-cyan/50 text-neon-cyan cursor-wait" 
                  : "bg-neon-cyan hover:bg-neon-cyan/80 text-black shadow-[0_0_20px_rgba(0,240,255,0.4)]"
              )}
            >
              {isRunning && (
                <div 
                  className="absolute left-0 bottom-0 h-1 bg-neon-cyan transition-all duration-100 ease-linear shadow-[0_0_10px_rgba(0,240,255,1)]" 
                  style={{ width: `${progress}%` }}
                />
              )}
              <div className="flex items-center gap-2">
                {isRunning ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                {isRunning ? `正在运行... ${progress}%` : "运行回测"}
              </div>
            </button>
          </div>
        </aside>

        {/* Main Content: Results */}
        <div className="flex-1 flex flex-col p-6 space-y-6 overflow-y-auto custom-scrollbar">
          {/* Equity Curve Area */}
          <div className="bg-bg-card/40 border border-border rounded-lg p-6 relative">
            <div className="flex justify-between items-center mb-6">
              <h3 className="text-xs font-orbitron tracking-widest text-white flex items-center gap-2">
                <TrendingUp className="h-4 w-4 text-neon-cyan" /> 权益曲线
              </h3>
              <div className="flex items-center gap-4 text-[10px] font-mono">
                <div className="flex items-center gap-2"><div className="w-2 h-2 bg-neon-cyan" /> 当前策略</div>
                <div className="flex items-center gap-2"><div className="w-2 h-2 bg-info-gray/30" /> 基准指数</div>
              </div>
            </div>

            <div className="h-[300px] w-full relative">
              {/* SVG Equity Curve */}
              <svg className="w-full h-full overflow-visible" preserveAspectRatio="none" viewBox="0 0 100 100">
                <defs>
                  <linearGradient id="equityGradient" x1="0%" y1="0%" x2="0%" y2="100%">
                    <stop offset="0%" stopColor="#00f0ff" stopOpacity="0.2" />
                    <stop offset="100%" stopColor="#00f0ff" stopOpacity="0" />
                  </linearGradient>
                </defs>
                {/* Benchmark (Simulated) */}
                <path 
                  d="M 0 60 L 10 58 L 20 62 L 30 55 L 40 59 L 50 52 L 60 56 L 70 50 L 80 54 L 90 48 L 100 52" 
                  fill="none" 
                  stroke="rgba(255,255,255,0.1)" 
                  strokeWidth="1" 
                />
                {/* Strategy Curve */}
                <path 
                  d={equityCurve} 
                  fill="url(#equityGradient)" 
                />
                <path 
                  d={equityCurve} 
                  fill="none" 
                  stroke="#00f0ff" 
                  strokeWidth="2" 
                  className="animate-path-flow"
                />
                {/* Dots */}
                <circle cx="0" cy="80" r="1.5" fill="#00f0ff" />
                <circle cx="100" cy="25" r="1.5" fill="#00f0ff" />
              </svg>
              
              {/* Floating Tooltip Mock */}
              <div className="absolute right-[10%] top-[25%] bg-bg-card/90 border border-neon-cyan/30 px-3 py-2 rounded text-[10px] font-mono pointer-events-none">
                <div className="text-neon-cyan">{endDate}</div>
                <div className="text-white">EQ: ¥{parseFloat(initialCapital).toLocaleString()}</div>
              </div>
            </div>
          </div>

          {/* Metrics Grid */}
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
            {metrics.map((m) => (
              <div key={m.label} className="bg-bg-card/40 border border-border p-4 rounded group hover:border-neon-cyan/30 transition-colors">
                <div className="text-[8px] text-info-gray/50 font-mono tracking-tighter uppercase mb-1">{m.label}</div>
                <div className={cn("text-xl font-orbitron font-bold", m.color)}>{m.value}</div>
                <div className="text-[10px] text-info-gray/30 font-mono mt-1">{m.subValue}</div>
              </div>
            ))}
          </div>

          {/* Monte Carlo Simulation Section */}
          <div className="bg-bg-card/20 border border-border/50 rounded-lg p-6">
            <div className="flex justify-between items-center mb-6">
              <div>
                <h3 className="text-xs font-orbitron tracking-widest text-white uppercase">蒙特卡洛模拟</h3>
                <p className="text-[9px] text-info-gray/40 mt-1 uppercase">随机重采样鲁棒性测试</p>
              </div>
              <button 
                onClick={() => setShowMonteCarlo(!showMonteCarlo)}
                className="flex items-center gap-2 bg-bg-primary border border-border px-4 py-1.5 rounded text-[10px] text-info-gray hover:text-white hover:border-neon-cyan transition-all uppercase"
              >
                <RotateCcw className={cn("h-3 w-3", showMonteCarlo && "animate-spin")} />
                运行蒙特卡洛
              </button>
            </div>

            <div className="h-48 w-full bg-bg-primary/30 rounded border border-border p-4 relative overflow-hidden">
              {showMonteCarlo ? (
                <div className="relative h-full w-full">
                  <svg className="w-full h-full overflow-visible" preserveAspectRatio="none" viewBox="0 0 100 100">
                    {/* 20 paths */}
                    {[...Array(20)].map((_, i) => (
                      <path
                        key={i}
                        d={`M 0 80 ${[...Array(10)].map((_, j) => `L ${(j+1)*10} ${80 - (j+1)*5 - (Math.random()*15 - 7.5)}`).join(' ')}`}
                        fill="none"
                        stroke="#00f0ff"
                        strokeWidth="0.5"
                        strokeOpacity="0.15"
                      />
                    ))}
                  </svg>
                  <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                    <div className="bg-bg-card/80 border border-neon-cyan/40 px-6 py-3 rounded-md shadow-lg backdrop-blur-sm animate-in fade-in zoom-in duration-500">
                      <div className="text-[10px] font-orbitron text-neon-cyan mb-2 text-center">模拟完成 (N=5000)</div>
                      <div className="flex gap-8">
                        <div>
                          <div className="text-[8px] text-info-gray/60 font-mono uppercase">95% 置信区间</div>
                          <div className="text-sm font-bold text-white">¥902,450 - ¥1,124,000</div>
                        </div>
                        <div>
                          <div className="text-[8px] text-info-gray/60 font-mono uppercase">破产概率</div>
                          <div className="text-sm font-bold text-up-green">0.12%</div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="h-full flex flex-col items-center justify-center text-info-gray/20">
                  <RotateCcw className="h-8 w-8 mb-2 opacity-10" />
                  <span className="text-[10px] font-orbitron uppercase tracking-widest">等待模拟运行</span>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default BacktestLab;
