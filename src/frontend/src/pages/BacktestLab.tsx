import React, { useEffect, useState } from 'react';
import { Play, Settings, TrendingUp, BarChart, RotateCcw, Plus, Trash2, Loader2 } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { cn } from '../lib/utils';
import { apiUrl, monitorApi, strategyApi } from '../services/api';
import type { StrategyBacktestGridRequest } from '../api/generated/openapi-types';

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
  createdAt: number | null;
  metrics: Record<string, unknown>;
}

interface BacktestCompareRow {
  label: string;
  left: number | null;
  right: number | null;
  leftDisplay: string;
  rightDisplay: string;
  deltaDisplay: string;
  deltaPositive: boolean | null;
}

interface BacktestRunSnapshot {
  reportId: string;
  createdAt: number | null;
  finalEquity: number | null;
  barsCount: number;
  ticker: string;
  barRange: string;
}

interface GridResultRow {
  index?: number;
  parameters?: Record<string, unknown>;
  metrics?: Record<string, unknown>;
  summary?: Record<string, unknown>;
  gate?: Record<string, unknown>;
  archive?: Record<string, unknown>;
}

interface GridRunSnapshot {
  totalRuns: number;
  topK: number;
  sortBy: string;
  bestIndex: number | null;
  bestNetPnl: number | null;
}

interface BacktestInputBar {
  ts: string;
  close: number;
  signal: 'AUTO';
}

const parsePayloadData = <T,>(payload: unknown): T => {
  if (payload && typeof payload === 'object' && 'data' in payload) {
    return (payload as { data: T }).data;
  }
  return payload as T;
};

const normalizeTradeDate = (value: unknown): string => {
  if (typeof value === 'number' && Number.isFinite(value)) {
    const num = Math.trunc(value);
    const text = String(num);
    if (text.length === 8) {
      return `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6, 8)}`;
    }
    const millis = num > 1_000_000_000_000 ? num : num > 1_000_000_000 ? num * 1000 : 0;
    if (millis > 0) {
      return new Date(millis).toISOString().slice(0, 10);
    }
  }
  if (typeof value === 'string') {
    const text = value.trim();
    if (!text) return '';
    if (/^\d{8}$/.test(text)) {
      return `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6, 8)}`;
    }
    const parsed = Date.parse(text);
    if (!Number.isNaN(parsed)) {
      return new Date(parsed).toISOString().slice(0, 10);
    }
  }
  return '';
};

const normalizeBacktestBars = (payload: unknown, maxBars = 240): BacktestInputBar[] => {
  const raw = payload && typeof payload === 'object' && 'data' in payload
    ? (payload as { data?: unknown }).data
    : payload;
  if (!Array.isArray(raw)) {
    return [];
  }

  const rows: Array<{ key: number; bar: BacktestInputBar }> = [];
  raw.forEach((item, index) => {
    if (Array.isArray(item) && item.length >= 3) {
      const ts = normalizeTradeDate(item[0]);
      const close = Number(item[2]);
      const key = Date.parse(ts);
      if (ts && Number.isFinite(close) && close > 0 && Number.isFinite(key)) {
        rows.push({ key, bar: { ts, close, signal: 'AUTO' } });
      }
      return;
    }
    if (!item || typeof item !== 'object') {
      return;
    }
    const row = item as Record<string, unknown>;
    const ts = normalizeTradeDate(row.ts ?? row.timestamp ?? row.date ?? row.time ?? row.trade_date ?? row.datetime);
    const close = Number(row.close ?? row.c ?? row.price);
    const key = Date.parse(ts);
    if (ts && Number.isFinite(close) && close > 0 && Number.isFinite(key)) {
      rows.push({ key, bar: { ts, close, signal: 'AUTO' } });
    } else if (ts && Number.isFinite(close) && close > 0) {
      rows.push({ key: index, bar: { ts, close, signal: 'AUTO' } });
    }
  });

  rows.sort((a, b) => a.key - b.key);
  const normalized = rows.map((item) => item.bar);
  if (normalized.length > maxBars) {
    return normalized.slice(normalized.length - maxBars);
  }
  return normalized;
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

const normalizeOptionalNumber = (value: unknown): number | null => {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
};

const normalizeOptionalPercent = (value: unknown): number | null => {
  const raw = normalizeOptionalNumber(value);
  if (raw === null) {
    return null;
  }
  return Math.abs(raw) <= 1 ? raw * 100 : raw;
};

const formatSignedPercent = (value: number | null, digits = 2): string => {
  if (value === null) {
    return '--';
  }
  return `${value >= 0 ? '+' : ''}${value.toFixed(digits)}%`;
};

const formatDrawdownPercent = (value: number | null, digits = 2): string => {
  if (value === null) {
    return '--';
  }
  return `-${Math.abs(value).toFixed(digits)}%`;
};

const formatDecimal = (value: number | null, digits = 2): string => {
  if (value === null) {
    return '--';
  }
  return value.toFixed(digits);
};

const formatCurrency = (value: number | null, digits = 0): string => {
  if (value === null) {
    return '--';
  }
  return value.toLocaleString('zh-CN', { maximumFractionDigits: digits });
};

const buildMetricsFromBacktest = (metrics: any, summary: any): Metric[] => {
  const totalReturn = normalizeOptionalPercent(metrics?.total_return);
  const annualizedRaw = Number(
    metrics?.annualized_return
    ?? metrics?.annual_return
    ?? metrics?.annualized
    ?? metrics?.cagr,
  );
  const annualized =
    Number.isFinite(annualizedRaw)
      ? (Math.abs(annualizedRaw) <= 1 ? annualizedRaw * 100 : annualizedRaw)
      : null;
  const maxDrawdown = normalizeOptionalPercent(metrics?.max_drawdown);
  const sharpe = normalizeOptionalNumber(metrics?.sharpe ?? metrics?.sharpe_ratio);
  const winRate = normalizeOptionalPercent(metrics?.win_rate);
  const tradeCount = normalizeOptionalNumber(metrics?.trade_count);
  const turnover = normalizeOptionalNumber(metrics?.turnover);
  const netPnl = normalizeOptionalNumber(metrics?.net_pnl);
  const finalEquity = normalizeOptionalNumber(summary?.final_equity);
  const tradeCountDisplay = tradeCount === null ? '--' : `${Math.round(tradeCount)} 笔交易`;

  return [
    {
      label: '总收益',
      value: formatSignedPercent(totalReturn, 2),
      subValue: netPnl === null ? '--' : `¥${formatCurrency(netPnl, 0)}`,
      color: totalReturn === null ? 'text-info-gray' : totalReturn >= 0 ? 'text-up-green' : 'text-down-red',
    },
    {
      label: '年化收益',
      value: annualized === null ? '--' : `${annualized >= 0 ? '+' : ''}${annualized.toFixed(2)}%`,
      subValue: annualized === null ? '后端未提供' : '真实值',
      color: annualized === null ? 'text-info-gray' : annualized >= 0 ? 'text-up-green' : 'text-down-red',
    },
    {
      label: '最大回撤',
      value: formatDrawdownPercent(maxDrawdown, 2),
      subValue: '风险',
      color: maxDrawdown === null ? 'text-info-gray' : 'text-up-red',
    },
    {
      label: '夏普比率',
      value: formatDecimal(sharpe, 2),
      subValue: '风险调整后',
      color: sharpe === null ? 'text-info-gray' : 'text-neon-cyan',
    },
    {
      label: '胜率',
      value: winRate === null ? '--' : `${winRate.toFixed(1)}%`,
      subValue: tradeCountDisplay,
      color: winRate === null ? 'text-info-gray' : 'text-info-gray',
    },
    {
      label: '换手率',
      value: formatDecimal(turnover, 2),
      subValue: finalEquity === null ? '期末权益 --' : `期末权益 ¥${formatCurrency(finalEquity, 0)}`,
      color: turnover === null ? 'text-info-gray' : 'text-warn-gold',
    },
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

const asOptionalPercent = (value: unknown): number | null => {
  const raw = normalizeOptionalNumber(value);
  if (raw === null) {
    return null;
  }
  return raw <= 1 ? raw * 100 : raw;
};

const formatOptionalFixed = (value: number | null, digits = 2): string => {
  if (value === null) {
    return '--';
  }
  return value.toFixed(digits);
};

const formatOptionalPercent = (value: number | null, digits = 2): string => {
  if (value === null) {
    return '--';
  }
  return `${value.toFixed(digits)}%`;
};

const formatOptionalInteger = (value: number | null): string => {
  if (value === null) {
    return '--';
  }
  return `${Math.round(value)}`;
};

const formatUnixSeconds = (value: number | null): string => {
  if (value === null || value <= 0) {
    return '--';
  }
  return new Date(value * 1000).toLocaleString('zh-CN');
};

const extractErrorMessage = (error: unknown): string => {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return String(error);
};

const parseGridScalarValue = (raw: string): unknown => {
  const text = raw.trim();
  if (!text) {
    return text;
  }
  if (/^(true|false)$/i.test(text)) {
    return text.toLowerCase() === 'true';
  }
  const numberValue = Number(text);
  if (Number.isFinite(numberValue)) {
    return numberValue;
  }
  return text;
};

const buildParameterGrid = (rows: Array<{ key: string; value: string }>): Record<string, unknown[]> => {
  const grid: Record<string, unknown[]> = {};
  rows.forEach((row) => {
    const key = row.key.trim();
    if (!key) {
      return;
    }
    const values = row.value
      .split(',')
      .map((item) => item.trim())
      .filter((item) => item.length > 0)
      .map((item) => parseGridScalarValue(item));
    if (values.length > 0) {
      grid[key] = values;
    }
  });
  return grid;
};

const parseReportSummary = (report: any): BacktestReportSummary => {
  const payload = (report?.report_payload?.backtest ?? report?.backtest ?? {}) as Record<string, unknown>;
  const metrics = (payload.metrics ?? report?.metrics ?? {}) as Record<string, unknown>;
  const strategyPayload = (payload.strategy ?? {}) as Record<string, unknown>;
  return {
    reportId: String(report?.id ?? ''),
    strategyName: String(report?.strategy_name ?? strategyPayload.name ?? 'Unknown'),
    createdAt: normalizeOptionalNumber(report?.created_at),
    metrics,
  };
};

const buildCompareRows = (left: BacktestReportSummary, right: BacktestReportSummary): BacktestCompareRow[] => {
  const rows: Array<Omit<BacktestCompareRow, 'deltaDisplay' | 'deltaPositive'>> = [
    {
      label: 'Net PnL',
      left: normalizeOptionalNumber(left.metrics.net_pnl),
      right: normalizeOptionalNumber(right.metrics.net_pnl),
      leftDisplay: formatOptionalFixed(normalizeOptionalNumber(left.metrics.net_pnl), 2),
      rightDisplay: formatOptionalFixed(normalizeOptionalNumber(right.metrics.net_pnl), 2),
    },
    {
      label: 'Win Rate',
      left: asOptionalPercent(left.metrics.win_rate),
      right: asOptionalPercent(right.metrics.win_rate),
      leftDisplay: formatOptionalPercent(asOptionalPercent(left.metrics.win_rate), 2),
      rightDisplay: formatOptionalPercent(asOptionalPercent(right.metrics.win_rate), 2),
    },
    {
      label: 'Sharpe',
      left: normalizeOptionalNumber(left.metrics.sharpe ?? left.metrics.sharpe_ratio),
      right: normalizeOptionalNumber(right.metrics.sharpe ?? right.metrics.sharpe_ratio),
      leftDisplay: formatOptionalFixed(normalizeOptionalNumber(left.metrics.sharpe ?? left.metrics.sharpe_ratio), 3),
      rightDisplay: formatOptionalFixed(normalizeOptionalNumber(right.metrics.sharpe ?? right.metrics.sharpe_ratio), 3),
    },
    {
      label: 'Max Drawdown',
      left: asOptionalPercent(left.metrics.max_drawdown),
      right: asOptionalPercent(right.metrics.max_drawdown),
      leftDisplay: formatOptionalPercent(asOptionalPercent(left.metrics.max_drawdown), 2),
      rightDisplay: formatOptionalPercent(asOptionalPercent(right.metrics.max_drawdown), 2),
    },
    {
      label: 'Trade Count',
      left: normalizeOptionalNumber(left.metrics.trade_count),
      right: normalizeOptionalNumber(right.metrics.trade_count),
      leftDisplay: formatOptionalInteger(normalizeOptionalNumber(left.metrics.trade_count)),
      rightDisplay: formatOptionalInteger(normalizeOptionalNumber(right.metrics.trade_count)),
    },
  ];

  return rows.map((row) => {
    if (row.left === null || row.right === null) {
      return {
        ...row,
        deltaDisplay: '--',
        deltaPositive: null,
      };
    }
    const delta = row.left - row.right;
    return {
      ...row,
      deltaDisplay: `${delta >= 0 ? '+' : ''}${delta.toFixed(3)}`,
      deltaPositive: delta >= 0,
    };
  });
};

export const BacktestLab: React.FC = () => {
  const [searchParams] = useSearchParams();
  const [isRunning, setIsRunning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [showMonteCarlo, setShowMonteCarlo] = useState(false);
  const [params, setParams] = useState([{ key: 'MA_PERIOD', value: '20' }, { key: 'RISK_PCT', value: '0.02' }]);
  const [strategyOptions, setStrategyOptions] = useState<StrategyOption[]>([]);
  const [strategyId, setStrategyId] = useState('');
  const [strategyLoading, setStrategyLoading] = useState(false);
  const [strategyLoadError, setStrategyLoadError] = useState('');
  const [ticker, setTicker] = useState('sh600000');
  const [startDate, setStartDate] = useState('2023-01-01');
  const [endDate, setEndDate] = useState('2024-04-01');
  const [initialCapital, setInitialCapital] = useState('1000000');
  const [barsLoading, setBarsLoading] = useState(false);
  const [barsSummary, setBarsSummary] = useState('');
  const [metrics, setMetrics] = useState<Metric[]>([]);
  const [equityCurve, setEquityCurve] = useState<string>('');
  const [runError, setRunError] = useState('');
  const [latestRun, setLatestRun] = useState<BacktestRunSnapshot | null>(null);
  const [compareLoading, setCompareLoading] = useState(false);
  const [compareError, setCompareError] = useState('');
  const [compareLeft, setCompareLeft] = useState<BacktestReportSummary | null>(null);
  const [compareRight, setCompareRight] = useState<BacktestReportSummary | null>(null);
  const [compareRows, setCompareRows] = useState<BacktestCompareRow[]>([]);
  const [gridRunning, setGridRunning] = useState(false);
  const [gridError, setGridError] = useState('');
  const [gridRows, setGridRows] = useState<GridResultRow[]>([]);
  const [gridBest, setGridBest] = useState<GridResultRow | null>(null);
  const [gridSnapshot, setGridSnapshot] = useState<GridRunSnapshot | null>(null);

  useEffect(() => {
    const loadStrategyOptions = async () => {
      setStrategyLoading(true);
      setStrategyLoadError('');
      try {
        const payload = await strategyApi.getVersions<{ items?: Array<Record<string, unknown>> } | Array<Record<string, unknown>>>(100);
        const data = parsePayloadData<{ items?: Array<Record<string, unknown>> } | Array<Record<string, unknown>>>(payload);
        const rows = Array.isArray(data)
          ? data
          : (data && typeof data === 'object' && Array.isArray((data as { items?: Array<Record<string, unknown>> }).items))
            ? (data as { items: Array<Record<string, unknown>> }).items
            : [];
        const options = rows.map((item: any) => ({
          id: String(item?.id ?? ''),
          name: String(item?.name ?? item?.id ?? 'Unknown Strategy'),
        })).filter((item: StrategyOption) => item.id);
        setStrategyOptions(options);
        setStrategyId((prev) => (options.some((o) => o.id === prev) ? prev : (options[0]?.id ?? '')));
        if (!options.length) {
          setStrategyLoadError('暂无可用策略版本，请先在策略矩阵创建策略。');
        }
      } catch (err) {
        setStrategyOptions([]);
        setStrategyId('');
        setStrategyLoadError(`策略列表加载失败: ${extractErrorMessage(err)}`);
        console.warn('[BacktestLab] load strategy options failed:', err);
      } finally {
        setStrategyLoading(false);
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

  const loadBacktestBars = async (): Promise<BacktestInputBar[]> => {
    const normalizedTicker = ticker.trim().toLowerCase();
    if (!normalizedTicker) {
      throw new Error('请输入回测标的代码。');
    }
    setBarsLoading(true);
    try {
      const payload = await monitorApi.getKline<unknown>(normalizedTicker, 240, 'daily');
      const bars = normalizeBacktestBars(payload, 240);
      if (bars.length < 2) {
        throw new Error(`标的 ${normalizedTicker.toUpperCase()} 可用 K 线不足（至少 2 条）。`);
      }
      const startTs = Date.parse(startDate);
      const endTs = Date.parse(endDate);
      const inRangeBars = Number.isFinite(startTs) && Number.isFinite(endTs)
        ? bars.filter((item) => {
            const current = Date.parse(item.ts);
            return Number.isFinite(current) && current >= startTs && current <= endTs;
          })
        : bars;
      if (inRangeBars.length < 2) {
        throw new Error(`标的 ${normalizedTicker.toUpperCase()} 在所选日期范围内可用 K 线不足（至少 2 条）。`);
      }
      const first = inRangeBars[0];
      const last = inRangeBars[inRangeBars.length - 1];
      setBarsSummary(`${normalizedTicker.toUpperCase()} ${first.ts} ~ ${last.ts}（${inRangeBars.length} bars）`);
      return inRangeBars;
    } finally {
      setBarsLoading(false);
    }
  };

  const runBacktest = async () => {
    if (!strategyId.trim() || strategyOptions.length === 0) {
      setRunError('请选择策略后再运行回测。');
      return;
    }
    const startTs = Date.parse(startDate);
    const endTs = Date.parse(endDate);
    if (!Number.isFinite(startTs) || !Number.isFinite(endTs) || endTs <= startTs) {
      setRunError('结束日期必须晚于开始日期。');
      return;
    }

    setRunError('');
    setIsRunning(true);
    setProgress(12);
    const progressTimer = window.setInterval(() => {
      setProgress((prev) => Math.min(prev + 6, 92));
    }, 220);

    try {
      const bars = await loadBacktestBars();
      setProgress((prev) => Math.max(prev, 36));
      const payload = {
        strategy_id: strategyId,
        bars,
        start_cash: Number.parseFloat(initialCapital) || 1_000_000,
        parameters_override: Object.fromEntries(params.filter((p) => p.key.trim()).map((p) => [p.key.trim(), p.value])),
      };

      const body = await strategyApi.runBacktest<Record<string, unknown>>(payload);
      const parsed = parsePayloadData<Record<string, unknown>>(body) || {};
      const backtest = (parsed.backtest as Record<string, unknown> | undefined) ?? null;
      if (!backtest) {
        throw new Error('后端未返回 backtest 数据。');
      }
      const backtestMetrics = (backtest.metrics as Record<string, unknown>) ?? {};
      const backtestSummary = (backtest.summary as Record<string, unknown>) ?? {};
      const equityCurveTail = Array.isArray(backtest.equity_curve_tail) ? backtest.equity_curve_tail : [];
      const archive = (parsed.archive && typeof parsed.archive === 'object')
        ? parsed.archive as Record<string, unknown>
        : {};
      const reportId = String(archive.id ?? '');
      const createdAt = normalizeOptionalNumber(archive.created_at);
      const finalEquity = normalizeOptionalNumber(backtestSummary.final_equity);

      setProgress(100);
      setMetrics(buildMetricsFromBacktest(backtestMetrics, backtestSummary));
      const curvePath = buildEquityPath(equityCurveTail);
      setEquityCurve(curvePath);
      setLatestRun({
        reportId,
        createdAt,
        finalEquity,
        barsCount: bars.length,
        ticker: ticker.trim().toUpperCase(),
        barRange: bars.length > 0 ? `${bars[0].ts} ~ ${bars[bars.length - 1].ts}` : '--',
      });
    } catch (error) {
      console.warn('[BacktestLab] runBacktest failed:', error);
      setRunError(`回测执行失败: ${extractErrorMessage(error)}`);
    } finally {
      window.clearInterval(progressTimer);
      window.setTimeout(() => {
        setIsRunning(false);
        setProgress(0);
      }, 180);
    }
  };

  const runMonteCarloGrid = async () => {
    if (!strategyId.trim() || strategyOptions.length === 0) {
      setGridError('请选择策略后再运行蒙特卡洛网格模拟。');
      return;
    }
    const startTs = Date.parse(startDate);
    const endTs = Date.parse(endDate);
    if (!Number.isFinite(startTs) || !Number.isFinite(endTs) || endTs <= startTs) {
      setGridError('结束日期必须晚于开始日期。');
      return;
    }

    setShowMonteCarlo(true);
    setGridError('');
    setGridRunning(true);
    try {
      const bars = await loadBacktestBars();
      const parameterGrid = buildParameterGrid(params);
      const combinationsEstimate = Object.values(parameterGrid).reduce(
        (acc, values) => acc * Math.max(1, values.length),
        1,
      );
      const maxCombinations = Math.min(Math.max(8, combinationsEstimate), 256);
      const payload: StrategyBacktestGridRequest = {
        strategy_id: strategyId,
        bars,
        parameter_grid: parameterGrid,
        max_combinations: maxCombinations,
        top_k: 5,
        sort_by: 'net_pnl',
        start_cash: Number.parseFloat(initialCapital) || 1_000_000,
        archive_report: true,
        evaluate_gate: true,
        persist_best_metrics: true,
        run_tag: `mc-${Date.now()}`,
      };
      const response = await strategyApi.runBacktestGrid<Record<string, unknown>>(payload);
      const parsed = parsePayloadData<Record<string, unknown>>(response) || {};
      const summary = (parsed.summary && typeof parsed.summary === 'object')
        ? (parsed.summary as Record<string, unknown>)
        : {};
      const topResults = Array.isArray(parsed.top_results) ? parsed.top_results as GridResultRow[] : [];
      const bestResult = (parsed.best && typeof parsed.best === 'object')
        ? (parsed.best as GridResultRow)
        : null;
      setGridRows(topResults);
      setGridBest(bestResult);
      setGridSnapshot({
        totalRuns: toNumber(summary.total_runs, topResults.length),
        topK: toNumber(summary.top_k, topResults.length),
        sortBy: String(summary.sort_by ?? 'net_pnl'),
        bestIndex: normalizeOptionalNumber(bestResult?.index),
        bestNetPnl: normalizeOptionalNumber((bestResult?.metrics ?? {}).net_pnl),
      });
    } catch (error) {
      setGridRows([]);
      setGridBest(null);
      setGridSnapshot(null);
      setGridError(`蒙特卡洛网格模拟失败: ${extractErrorMessage(error)}`);
    } finally {
      setGridRunning(false);
    }
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

      {runError && (
        <div className="mx-6 mt-4 rounded border border-down-red/30 bg-down-red/5 px-3 py-2 text-[11px] text-down-red">
          {runError}
        </div>
      )}

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
                  <div className="text-info-gray/60">{formatUnixSeconds(compareLeft.createdAt)}</div>
                </div>
                <div className="border border-border/40 rounded p-2">
                  <div className="text-info-gray/60 uppercase text-[9px]">Baseline</div>
                  <div className="text-white font-semibold">{compareRight.strategyName}</div>
                  <div className="text-info-gray/60">{formatUnixSeconds(compareRight.createdAt)}</div>
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
                      <span className={row.deltaPositive === null ? 'text-info-gray/60' : row.deltaPositive ? 'text-up-green' : 'text-down-red'}>
                        {row.deltaDisplay}
                      </span>
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
                disabled={strategyLoading || strategyOptions.length === 0}
                className="w-full bg-bg-primary border border-border rounded px-3 py-2 text-xs text-white outline-none focus:border-neon-cyan transition-colors"
              >
                {strategyOptions.length > 0
                  ? strategyOptions.map((option) => (
                    <option key={option.id} value={option.id}>{option.name}</option>
                  ))
                  : (
                    <option value="">{strategyLoading ? '加载策略中...' : '暂无可用策略'}</option>
                  )}
              </select>
              {strategyLoadError && (
                <div className="text-[9px] text-down-red/90">{strategyLoadError}</div>
              )}
            </div>

            <div className="space-y-2">
              <label className="text-[10px] text-info-gray uppercase font-bold tracking-wider">回测标的</label>
              <input
                type="text"
                value={ticker}
                onChange={(e) => setTicker(e.target.value)}
                placeholder="sh600000"
                className="w-full bg-bg-primary border border-border rounded px-3 py-2 text-xs text-white outline-none focus:border-neon-cyan transition-colors uppercase"
              />
              <div className="text-[9px] text-info-gray/55">
                {barsLoading ? '正在拉取真实 K 线...' : (barsSummary || '运行时将通过 monitorApi.getKline 拉取真实 K 线。')}
              </div>
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
              disabled={isRunning || barsLoading || !strategyId.trim() || strategyOptions.length === 0}
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
                {(isRunning || barsLoading) ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                {isRunning ? `正在运行... ${progress}%` : (barsLoading ? '加载 K 线中...' : "运行回测")}
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
                <div className="flex items-center gap-2"><div className="w-2 h-2 bg-neon-cyan" /> 当前策略曲线</div>
                {latestRun?.reportId && (
                  <button
                    onClick={() => window.open(apiUrl(`/api/strategy/backtests/${latestRun.reportId}`), '_blank', 'noopener,noreferrer')}
                    className="px-2 py-1 border border-neon-cyan/40 text-neon-cyan rounded hover:bg-neon-cyan/10 transition-colors"
                  >
                    查看报告
                  </button>
                )}
              </div>
            </div>

            <div className="h-[300px] w-full relative">
              {equityCurve ? (
                <svg className="w-full h-full overflow-visible" preserveAspectRatio="none" viewBox="0 0 100 100">
                  <defs>
                    <linearGradient id="equityGradient" x1="0%" y1="0%" x2="0%" y2="100%">
                      <stop offset="0%" stopColor="#00f0ff" stopOpacity="0.2" />
                      <stop offset="100%" stopColor="#00f0ff" stopOpacity="0" />
                    </linearGradient>
                  </defs>
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
                </svg>
              ) : (
                <div className="h-full flex items-center justify-center text-[11px] text-info-gray/60 border border-border/40 rounded">
                  暂无可展示的权益曲线，请先运行一次回测。
                </div>
              )}

              {latestRun && (
                <div className="absolute right-4 top-4 bg-bg-card/90 border border-neon-cyan/30 px-3 py-2 rounded text-[10px] font-mono space-y-1">
                  <div className="text-neon-cyan">最近回测</div>
                  <div className="text-white">报告ID: {latestRun.reportId || '--'}</div>
                  <div className="text-info-gray/80">标的: {latestRun.ticker || '--'}</div>
                  <div className="text-info-gray/80">K线点数: {latestRun.barsCount}</div>
                  <div className="text-info-gray/80">K线区间: {latestRun.barRange || '--'}</div>
                  <div className="text-info-gray/80">
                    期末权益: {latestRun.finalEquity === null ? '--' : `¥${formatCurrency(latestRun.finalEquity, 2)}`}
                  </div>
                  <div className="text-info-gray/70">
                    归档时间: {formatUnixSeconds(latestRun.createdAt)}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Metrics Grid */}
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
            {metrics.length > 0 ? (
              metrics.map((m) => (
                <div key={m.label} className="bg-bg-card/40 border border-border p-4 rounded group hover:border-neon-cyan/30 transition-colors">
                  <div className="text-[8px] text-info-gray/50 font-mono tracking-tighter uppercase mb-1">{m.label}</div>
                  <div className={cn("text-xl font-orbitron font-bold", m.color)}>{m.value}</div>
                  <div className="text-[10px] text-info-gray/30 font-mono mt-1">{m.subValue}</div>
                </div>
              ))
            ) : (
              <div className="col-span-2 md:col-span-3 lg:col-span-6 rounded border border-border bg-bg-card/20 px-4 py-10 text-center text-[11px] text-info-gray/60">
                暂无回测指标，请先运行回测。
              </div>
            )}
          </div>

          {/* Monte Carlo Simulation Section */}
          <div className="bg-bg-card/20 border border-border/50 rounded-lg p-6">
            <div className="flex justify-between items-center mb-6">
              <div>
                <h3 className="text-xs font-orbitron tracking-widest text-white uppercase">蒙特卡洛参数网格</h3>
                <p className="text-[9px] text-info-gray/40 mt-1 uppercase">结果来自 /api/strategy/backtest/grid 真实返回</p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => void runMonteCarloGrid()}
                  disabled={gridRunning || barsLoading || !strategyId.trim() || strategyOptions.length === 0}
                  className="flex items-center gap-2 bg-neon-cyan/10 border border-neon-cyan/40 px-4 py-1.5 rounded text-[10px] text-neon-cyan hover:bg-neon-cyan/20 transition-all uppercase disabled:opacity-60 disabled:cursor-not-allowed"
                >
                  {gridRunning ? <Loader2 className="h-3 w-3 animate-spin" /> : <RotateCcw className="h-3 w-3" />}
                  {gridRunning ? '运行中' : '运行模拟'}
                </button>
                <button
                  onClick={() => setShowMonteCarlo(!showMonteCarlo)}
                  className="flex items-center gap-2 bg-bg-primary border border-border px-4 py-1.5 rounded text-[10px] text-info-gray hover:text-white hover:border-neon-cyan transition-all uppercase"
                >
                  {showMonteCarlo ? '收起结果' : '展开结果'}
                </button>
              </div>
            </div>

            <div className="min-h-48 w-full bg-bg-primary/30 rounded border border-border p-4 relative overflow-hidden">
              {gridRunning ? (
                <div className="h-full min-h-40 flex items-center justify-center text-info-gray/70 text-[11px] gap-2">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  正在执行参数网格回测...
                </div>
              ) : gridError ? (
                <div className="h-full min-h-40 flex items-center justify-center">
                  <div className="max-w-2xl rounded border border-down-red/40 bg-down-red/5 px-4 py-3 text-[11px] text-down-red">
                    {gridError}
                  </div>
                </div>
              ) : showMonteCarlo ? (
                gridRows.length > 0 ? (
                  <div className="space-y-3 text-[11px]">
                    {gridSnapshot && (
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                        <div className="rounded border border-border/40 bg-bg-card/30 p-2">
                          <div className="text-info-gray/60 text-[9px] uppercase">总组合</div>
                          <div className="text-white font-semibold">{gridSnapshot.totalRuns}</div>
                        </div>
                        <div className="rounded border border-border/40 bg-bg-card/30 p-2">
                          <div className="text-info-gray/60 text-[9px] uppercase">TopK</div>
                          <div className="text-white font-semibold">{gridSnapshot.topK}</div>
                        </div>
                        <div className="rounded border border-border/40 bg-bg-card/30 p-2">
                          <div className="text-info-gray/60 text-[9px] uppercase">排序指标</div>
                          <div className="text-white font-semibold">{gridSnapshot.sortBy}</div>
                        </div>
                        <div className="rounded border border-border/40 bg-bg-card/30 p-2">
                          <div className="text-info-gray/60 text-[9px] uppercase">最佳净收益</div>
                          <div
                            className={
                              gridSnapshot.bestNetPnl === null
                                ? 'text-info-gray font-semibold'
                                : gridSnapshot.bestNetPnl >= 0
                                  ? 'text-up-green font-semibold'
                                  : 'text-down-red font-semibold'
                            }
                          >
                            {gridSnapshot.bestNetPnl === null ? '--' : gridSnapshot.bestNetPnl.toFixed(2)}
                          </div>
                        </div>
                      </div>
                    )}

                    <div className="grid gap-2">
                      {gridRows.map((row) => {
                        const metrics = row.metrics ?? {};
                        const netPnl = toNumber(metrics.net_pnl, 0);
                        const winRate = asPercent(metrics.win_rate);
                        const sharpe = toNumber(metrics.sharpe ?? metrics.sharpe_ratio, 0);
                        const drawdown = asPercent(metrics.max_drawdown);
                        const gatePassed = Boolean((row.gate ?? {}).passed);
                        return (
                          <div key={`${row.index ?? 0}-${JSON.stringify(row.parameters ?? {})}`} className="rounded border border-border/40 bg-bg-card/20 px-3 py-2">
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <div className="text-white font-semibold">组合 #{row.index ?? '--'}</div>
                              <div className={gatePassed ? 'text-up-green text-[10px]' : 'text-down-red text-[10px]'}>
                                {gatePassed ? 'Gate Passed' : 'Gate Failed'}
                              </div>
                            </div>
                            <div className="mt-1 text-[10px] text-info-gray/75">
                              参数: {JSON.stringify(row.parameters ?? {})}
                            </div>
                            <div className="mt-2 grid grid-cols-2 md:grid-cols-4 gap-2 text-[10px]">
                              <span className={netPnl >= 0 ? 'text-up-green' : 'text-down-red'}>NetPnL {netPnl.toFixed(2)}</span>
                              <span className="text-white">WinRate {winRate.toFixed(2)}%</span>
                              <span className="text-neon-cyan">Sharpe {sharpe.toFixed(3)}</span>
                              <span className="text-warn-gold">MaxDD {drawdown.toFixed(2)}%</span>
                            </div>
                          </div>
                        );
                      })}
                    </div>

                    {gridBest && (
                      <div className="rounded border border-neon-cyan/40 bg-neon-cyan/5 px-3 py-2 text-[10px] text-info-gray/80">
                        最佳组合索引：{gridBest.index ?? '--'}，参数：{JSON.stringify(gridBest.parameters ?? {})}
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="h-full min-h-40 flex items-center justify-center text-[11px] text-info-gray/60">
                    尚未运行网格模拟，点击“运行模拟”获取真实结果。
                  </div>
                )
              ) : (
                <div className="h-full min-h-40 flex flex-col items-center justify-center text-info-gray/35">
                  <RotateCcw className="h-8 w-8 mb-2 opacity-40" />
                  <span className="text-[10px] font-orbitron uppercase tracking-widest">已接入网格回测，点击展开结果</span>
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
