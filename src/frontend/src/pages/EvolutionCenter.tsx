import { useState, useEffect, useCallback, useMemo, FC, cloneElement } from 'react';
import {
  Activity,
  Crosshair,
  Eye,
  GitBranch,
  History,
  Info,
  Layers,
  Loader2,
  Play,
  RefreshCw,
  Search,
  Shield,
  Target,
  Zap,
} from 'lucide-react';
import { cn } from '../lib/utils';
import { PageTitle } from '../components/PageTitle';
import { apiUrl, strategyApi } from '../services/api';

type StrategyType = 'BASE' | 'FIX' | 'DERIVED' | 'CAPTURED' | 'MUTATION' | 'CROSSOVER' | 'UNKNOWN';
type StrategyStatus = 'ACTIVE' | 'EVOLVING' | 'PAUSED' | 'CANDIDATE' | 'RETIRED' | 'DRAFT' | 'REJECTED' | 'UNKNOWN';
type EvolutionTab = 'Overview' | 'Tree' | 'OODA' | 'Comparison';

interface Strategy {
  id: string;
  name: string;
  version: number | null;
  quality: number | null;
  gatePassed: boolean | null;
  status: StrategyStatus;
  type: StrategyType;
  parentId?: string;
  createdAt: string;
  description: string;
  returns: number[];
  maxDrawdown: number | null;
  sharpe: number | null;
  winRate: number | null;
  tradeCount: number | null;
  netPnl: number | null;
  latestBacktestId?: string;
}

interface EvolutionEvent {
  id: string;
  timestamp: string;
  type: StrategyType;
  strategyName: string;
  message: string;
  ooda?: {
    observe?: string;
    orient?: string;
    decide?: string;
    act?: string;
    trades?: number | null;
    pnl?: number | null;
    deviations?: number | null;
  };
}

interface OODALog {
  id: string;
  date: string;
  observe: string;
  orient: string;
  decide: string;
  act: string;
  trades: number | null;
  pnl: number | null;
  deviations: number | null;
}

interface VersionMetricDelta {
  current: number;
  baseline: number;
  delta: number;
}

interface VersionContentFieldDiff {
  field: string;
  status: 'added' | 'removed' | 'changed';
  current_value: string;
  baseline_value: string;
}

interface VersionContentLineDiff {
  type: string;
  baseline_range: [number, number];
  current_range: [number, number];
  baseline_lines: string[];
  current_lines: string[];
}

interface VersionDiffPayload {
  strategy_id: string;
  baseline_id: string;
  baseline_source: string;
  has_baseline: boolean;
  current: {
    id: string;
    name: string;
    version: number;
    status: string;
  };
  baseline: {
    id: string;
    name: string;
    version: number;
    status: string;
  } | null;
  metric_diff: Record<string, VersionMetricDelta>;
  parameter_diff: {
    added: string[];
    removed: string[];
    changed: string[];
  };
  content_changed: boolean;
  content_diff?: {
    mode: 'json_fields' | 'text_lines';
    changed: boolean;
    summary?: Record<string, number>;
    fields?: VersionContentFieldDiff[];
    changes?: VersionContentLineDiff[];
    truncated?: boolean;
  };
  backtest_compare?: {
    current_report_id: string;
    baseline_report_id: string;
    current_report_created_at: number;
    baseline_report_created_at: number;
    compare_ready: boolean;
    compare_page_url: string;
    current_report_url: string;
    baseline_report_url: string;
  };
}

const TABS: Array<{ value: EvolutionTab; label: string }> = [
  { value: 'Overview', label: '概览' },
  { value: 'Tree', label: '演进树' },
  { value: 'OODA', label: 'OODA' },
  { value: 'Comparison', label: '策略对比' },
];

const toNumber = (value: unknown, fallback = 0): number => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};

const clamp = (value: number, min: number, max: number): number => Math.max(min, Math.min(max, value));

const toTimestamp = (value: unknown): number => {
  if (typeof value === 'string' && value.trim()) {
    const parsed = Date.parse(value);
    if (!Number.isNaN(parsed)) {
      return parsed;
    }
  }
  const num = toNumber(value, 0);
  if (num <= 0) {
    return 0;
  }
  return num > 1_000_000_000_000 ? num : num * 1000;
};

const toISOString = (value: unknown): string => {
  const ts = toTimestamp(value);
  if (ts > 0) {
    return new Date(ts).toISOString();
  }
  return '';
};

const parsePayloadData = <T,>(payload: unknown): T => {
  if (payload && typeof payload === 'object' && 'data' in payload) {
    return (payload as { data: T }).data;
  }
  return payload as T;
};

const normalizeOptionalRatio = (value: unknown): number | null => {
  const raw = Number(value);
  if (!Number.isFinite(raw)) {
    return null;
  }
  const ratio = raw > 1 ? raw / 100 : raw;
  return clamp(ratio, 0, 1);
};

const normalizeQualityScore = (value: unknown): number | null => {
  const raw = Number(value);
  if (!Number.isFinite(raw)) {
    return null;
  }
  const ratio = Math.abs(raw) > 1 ? raw / 100 : raw;
  return clamp(ratio, 0, 1);
};

const normalizeDisplayText = (value: unknown, fallback = '--'): string => {
  const text = String(value ?? '').trim();
  return text.length > 0 ? text : fallback;
};

const normalizeOptionalNumber = (value: unknown): number | null => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

const normalizeOptionalCount = (value: unknown): number | null => {
  const parsed = normalizeOptionalNumber(value);
  if (parsed === null) {
    return null;
  }
  return Math.max(0, Math.round(parsed));
};

const normalizeOptionalVersion = (value: unknown): number | null => {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return null;
  }
  const version = Math.trunc(parsed);
  return version > 0 ? version : null;
};

const formatLocalDate = (value: unknown): string => {
  const ts = toTimestamp(value);
  if (ts <= 0) {
    return '--';
  }
  return new Date(ts).toLocaleDateString();
};

const formatLocalTime = (value: unknown): string => {
  const ts = toTimestamp(value);
  if (ts <= 0) {
    return '--';
  }
  return new Date(ts).toLocaleTimeString();
};

const formatPercent = (value: number | null, digits = 1): string => {
  if (value === null) {
    return '--';
  }
  return `${(value * 100).toFixed(digits)}%`;
};

const formatDecimal = (value: number | null, digits = 2): string => {
  if (value === null) {
    return '--';
  }
  return value.toFixed(digits);
};

const formatVersionLabel = (value: number | null): string => {
  if (value === null) {
    return '--';
  }
  return `v${value}`;
};

const normalizeType = (value: unknown): StrategyType => {
  const raw = String(value ?? '').trim().toUpperCase();
  const fromOrigin: Record<string, StrategyType> = {
    BUILT_IN: 'BASE',
    BACKTEST: 'FIX',
    MUTATION: 'MUTATION',
    CROSSOVER: 'CROSSOVER',
    CAPTURED: 'CAPTURED',
    DERIVED: 'DERIVED',
    FIX: 'FIX',
    BASE: 'BASE',
    UNKNOWN: 'UNKNOWN',
  };
  return fromOrigin[raw] ?? 'UNKNOWN';
};

const normalizeStatus = (value: unknown): StrategyStatus => {
  const raw = String(value ?? '').trim().toUpperCase();
  const map: Record<string, StrategyStatus> = {
    ACTIVE: 'ACTIVE',
    EVOLVING: 'EVOLVING',
    PAUSED: 'PAUSED',
    CANDIDATE: 'CANDIDATE',
    RETIRED: 'RETIRED',
    DRAFT: 'DRAFT',
    REJECTED: 'REJECTED',
    UNKNOWN: 'UNKNOWN',
  };
  return map[raw] ?? 'UNKNOWN';
};

const extractCurve = (metrics: Record<string, unknown>): number[] => {
  const curveKeys = ['equity_curve', 'returns_curve', 'returns', 'daily_returns', 'pnl_curve', 'net_value_curve'];
  for (const key of curveKeys) {
    const value = metrics[key];
    if (!Array.isArray(value)) {
      continue;
    }
    const points = value
      .map((item) => toNumber(item, Number.NaN))
      .filter((item) => Number.isFinite(item))
      .slice(-20);
    if (points.length >= 2) {
      return points;
    }
  }
  return [];
};

const typeColorClass = (type: StrategyType): string => {
  if (type === 'BASE') {
    return 'text-neon-cyan border-neon-cyan/30 bg-neon-cyan/10';
  }
  if (type === 'FIX') {
    return 'text-warn-gold border-warn-gold/30 bg-warn-gold/10';
  }
  if (type === 'CAPTURED') {
    return 'text-up-green border-up-green/30 bg-up-green/10';
  }
  if (type === 'MUTATION' || type === 'CROSSOVER') {
    return 'text-neon-magenta border-neon-magenta/30 bg-neon-magenta/10';
  }
  return 'text-info-gray border-info-gray/30 bg-info-gray/10';
};

const eventTypeBadgeClass = (type: StrategyType): string => {
  if (type === 'FIX') {
    return 'bg-warn-gold/20 text-warn-gold';
  }
  if (type === 'MUTATION' || type === 'CROSSOVER') {
    return 'bg-neon-magenta/20 text-neon-magenta';
  }
  if (type === 'BASE') {
    return 'bg-neon-cyan/20 text-neon-cyan';
  }
  if (type === 'CAPTURED') {
    return 'bg-up-green/20 text-up-green';
  }
  return 'bg-info-gray/20 text-info-gray';
};

const MiniSparkline: FC<{ data: number[]; color?: string }> = ({ data, color = '#00f0ff' }) => {
  if (data.length < 2) {
    return (
      <div className="flex h-[30px] w-[100px] items-center justify-center rounded border border-dashed border-border/50 text-[9px] text-info-gray/60">
        无曲线
      </div>
    );
  }
  const safeData = data;
  const min = Math.min(...safeData);
  const max = Math.max(...safeData);
  const range = Math.max(1e-6, max - min);
  const width = 100;
  const height = 30;
  const points = safeData
    .map((value, index) => `${(index / Math.max(1, safeData.length - 1)) * width},${height - ((value - min) / range) * height}`)
    .join(' ');

  return (
    <svg width={width} height={height} className="overflow-visible">
      <polyline points={points} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  );
};

export const EvolutionCenter: FC = () => {
  const [activeTab, setActiveTab] = useState<EvolutionTab>('Overview');
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [events, setEvents] = useState<EvolutionEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [searchKeyword, setSearchKeyword] = useState('');
  const [versionDiff, setVersionDiff] = useState<VersionDiffPayload | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const [diffError, setDiffError] = useState('');

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [versionsResult, historyResult, backtestsResult] = await Promise.allSettled([
        strategyApi.getVersions<{ items?: Array<Record<string, unknown>> } | Array<Record<string, unknown>>>(),
        strategyApi.getHistory<Array<Record<string, unknown>>>(),
        strategyApi.getBacktests<{ items?: Array<Record<string, unknown>> } | Array<Record<string, unknown>>>(200),
      ]);

      const backtestListRaw =
        backtestsResult.status === 'fulfilled'
          ? parsePayloadData<{ items?: Array<Record<string, unknown>> } | Array<Record<string, unknown>>>(backtestsResult.value)
          : [];
      const backtestItems = Array.isArray(backtestListRaw)
        ? backtestListRaw
        : Array.isArray(backtestListRaw?.items)
          ? backtestListRaw.items
          : [];

      const latestBacktestByStrategy = new Map<string, Record<string, unknown>>();
      for (const item of backtestItems) {
        const sid = String(item.strategy_id ?? '');
        if (!sid) {
          continue;
        }
        const existing = latestBacktestByStrategy.get(sid);
        if (!existing || toTimestamp(item.created_at) > toTimestamp(existing.created_at)) {
          latestBacktestByStrategy.set(sid, item);
        }
      }

      if (versionsResult.status === 'fulfilled') {
        const versionsPayload = parsePayloadData<{ items?: Array<Record<string, unknown>> } | Array<Record<string, unknown>>>(
          versionsResult.value,
        );
        const versionItems = Array.isArray(versionsPayload)
          ? versionsPayload
          : Array.isArray(versionsPayload?.items)
            ? versionsPayload.items
            : [];

        const mappedStrategies = versionItems.map((item) => {
          const id = String(item.id ?? '');
          const metrics = (item.metrics as Record<string, unknown>) ?? {};
          const latestBacktest = latestBacktestByStrategy.get(id) ?? {};
          const backtestMetrics = (latestBacktest.metrics as Record<string, unknown>) ?? {};
          const mergedMetrics = { ...metrics, ...backtestMetrics };
          const curve = extractCurve(mergedMetrics);

          const quality = normalizeQualityScore(mergedMetrics.quality_score);
          const versionGate =
            mergedMetrics.version_gate && typeof mergedMetrics.version_gate === 'object'
              ? (mergedMetrics.version_gate as Record<string, unknown>)
              : null;
          const gatePassedRaw = versionGate?.passed;
          const gatePassed = typeof gatePassedRaw === 'boolean' ? gatePassedRaw : null;

          return {
            id,
            name: normalizeDisplayText(item.name ?? item.id),
            version: normalizeOptionalVersion(item.version),
            quality,
            gatePassed,
            status: normalizeStatus(item.status),
            type: normalizeType(item.evolution_type ?? item.origin),
            parentId: item.parent_id ? String(item.parent_id) : undefined,
            createdAt: toISOString(item.created_at),
            description: normalizeDisplayText(item.description ?? item.content),
            returns: curve,
            maxDrawdown: normalizeOptionalRatio(mergedMetrics.max_drawdown),
            sharpe: normalizeOptionalNumber(mergedMetrics.sharpe_ratio ?? mergedMetrics.sharpe),
            winRate: normalizeOptionalRatio(mergedMetrics.win_rate),
            tradeCount: normalizeOptionalCount(mergedMetrics.trade_count),
            netPnl: normalizeOptionalNumber(mergedMetrics.net_pnl ?? mergedMetrics.total_pnl),
            latestBacktestId: String(latestBacktest.id ?? ''),
          } satisfies Strategy;
        });

        setStrategies(mappedStrategies);
        setSelectedId((current) => {
          if (current && mappedStrategies.some((strategy) => strategy.id === current)) {
            return current;
          }
          return mappedStrategies[0]?.id ?? null;
        });
      } else {
        setStrategies([]);
        setSelectedId(null);
      }

      if (historyResult.status === 'fulfilled') {
        const historyPayload = parsePayloadData<Array<Record<string, unknown>>>(historyResult.value);
        const historyItems = Array.isArray(historyPayload) ? historyPayload : [];
        setEvents(
          historyItems
            .map((item) => {
              const rawOoda = item.ooda && typeof item.ooda === 'object' ? (item.ooda as Record<string, unknown>) : null;
              return {
                id: String(item.id ?? ''),
                timestamp: toISOString(item.timestamp),
                type: normalizeType(item.type),
                strategyName: normalizeDisplayText(item.strategy_name),
                message: normalizeDisplayText(item.message, ''),
                ooda: rawOoda
                  ? {
                      observe: normalizeDisplayText(rawOoda.observe, ''),
                      orient: normalizeDisplayText(rawOoda.orient, ''),
                      decide: normalizeDisplayText(rawOoda.decide, ''),
                      act: normalizeDisplayText(rawOoda.act, ''),
                      trades: normalizeOptionalCount(rawOoda.trades),
                      pnl: normalizeOptionalNumber(rawOoda.pnl),
                      deviations: normalizeOptionalCount(rawOoda.deviations),
                    }
                  : undefined,
              } satisfies EvolutionEvent;
            })
            .sort((a, b) => toTimestamp(b.timestamp) - toTimestamp(a.timestamp)),
        );
      } else {
        setEvents([]);
      }
    } catch (error) {
      console.warn('[EvolutionCenter] 鏁版嵁鎷夊彇澶辫触:', error);
      setStrategies([]);
      setEvents([]);
      setSelectedId(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  useEffect(() => {
    setVersionDiff(null);
    setDiffError('');
    setDiffLoading(false);
  }, [selectedId]);

  const filteredStrategies = useMemo(() => {
    const keyword = searchKeyword.trim().toLowerCase();
    if (!keyword) {
      return strategies;
    }
    return strategies.filter((strategy) => {
      return (
        strategy.name.toLowerCase().includes(keyword)
        || strategy.type.toLowerCase().includes(keyword)
        || strategy.status.toLowerCase().includes(keyword)
      );
    });
  }, [searchKeyword, strategies]);

  const strategiesById = useMemo(() => {
    const mapping = new Map<string, Strategy>();
    for (const strategy of strategies) {
      mapping.set(strategy.id, strategy);
    }
    return mapping;
  }, [strategies]);

  const childrenByParent = useMemo(() => {
    const mapping = new Map<string, Strategy[]>();
    for (const strategy of strategies) {
      if (!strategy.parentId) {
        continue;
      }
      if (!mapping.has(strategy.parentId)) {
        mapping.set(strategy.parentId, []);
      }
      mapping.get(strategy.parentId)?.push(strategy);
    }
    for (const [parentId, children] of mapping.entries()) {
      mapping.set(
        parentId,
        [...children].sort((a, b) => toTimestamp(b.createdAt) - toTimestamp(a.createdAt)),
      );
    }
    return mapping;
  }, [strategies]);

  const rootStrategies = useMemo(() => {
    return strategies
      .filter((strategy) => !strategy.parentId || !strategiesById.has(strategy.parentId))
      .sort((a, b) => toTimestamp(b.createdAt) - toTimestamp(a.createdAt));
  }, [strategies, strategiesById]);

  const selectedStrategy =
    filteredStrategies.find((strategy) => strategy.id === selectedId)
    || strategies.find((strategy) => strategy.id === selectedId)
    || filteredStrategies[0]
    || strategies[0]
    || null;

  const evolutionDepth = useMemo(() => {
    let maxDepth = 0;
    const walk = (strategy: Strategy, depth: number) => {
      maxDepth = Math.max(maxDepth, depth);
      const children = childrenByParent.get(strategy.id) ?? [];
      for (const child of children) {
        walk(child, depth + 1);
      }
    };
    for (const root of rootStrategies) {
      walk(root, 1);
    }
    return maxDepth;
  }, [childrenByParent, rootStrategies]);

  const complianceRateText = useMemo(() => {
    const knownStrategies = strategies.filter((strategy) => strategy.gatePassed !== null);
    if (knownStrategies.length === 0) {
      return '--';
    }
    const passedCount = knownStrategies.filter((strategy) => strategy.gatePassed).length;
    return `${((passedCount / knownStrategies.length) * 100).toFixed(1)}%`;
  }, [strategies]);

  const todayEvolutionCount = useMemo(() => {
    const now = new Date();
    const start = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    const end = start + 24 * 3600 * 1000;
    return events.filter((event) => {
      const ts = toTimestamp(event.timestamp);
      return ts >= start && ts < end;
    }).length;
  }, [events]);

  const oodaLogs = useMemo(() => {
    if (events.length === 0) {
      return [];
    }

    const sourceEvents = events.slice(0, 12);

    return sourceEvents.map((event, index) => {
      const ooda = event.ooda;
      const observe = ooda?.observe?.trim() || event.message || '--';
      const orient = ooda?.orient?.trim() || '--';
      const decide = ooda?.decide?.trim() || '--';
      const act = ooda?.act?.trim() || '--';

      return {
        id: event.id || `ooda-${index}`,
        date: formatLocalDate(event.timestamp),
        observe,
        orient,
        decide,
        act,
        trades: normalizeOptionalCount(ooda?.trades),
        pnl: normalizeOptionalNumber(ooda?.pnl),
        deviations: normalizeOptionalCount(ooda?.deviations),
      } satisfies OODALog;
    });
  }, [events]);

  const comparisonStrategies = useMemo(() => {
    return [...strategies]
      .sort((a, b) => {
        const left = a.quality ?? Number.NEGATIVE_INFINITY;
        const right = b.quality ?? Number.NEGATIVE_INFINITY;
        return right - left;
      })
      .slice(0, 8);
  }, [strategies]);

  const handleOpenBacktest = () => {
    if (!selectedStrategy?.latestBacktestId) {
      return;
    }
    const reportUrl = apiUrl(`/api/strategy/backtests/${selectedStrategy.latestBacktestId}`);
    window.open(reportUrl, '_blank', 'noopener,noreferrer');
  };

  const handleLoadVersionDiff = async () => {
    if (!selectedStrategy?.id) {
      return;
    }
    setDiffLoading(true);
    setDiffError('');
    try {
      const payload = await strategyApi.getVersionDiff<VersionDiffPayload>(selectedStrategy.id);
      const diff = parsePayloadData<VersionDiffPayload>(payload);
      setVersionDiff(diff);
    } catch (error) {
      setVersionDiff(null);
      setDiffError(String(error));
    } finally {
      setDiffLoading(false);
    }
  };

  const diffMetricRows = useMemo(() => {
    if (!versionDiff?.metric_diff) {
      return [];
    }
    return Object.entries(versionDiff.metric_diff);
  }, [versionDiff]);

  const contentFieldRows = useMemo(() => {
    if (versionDiff?.content_diff?.mode !== 'json_fields') {
      return [];
    }
    return Array.isArray(versionDiff.content_diff.fields) ? versionDiff.content_diff.fields : [];
  }, [versionDiff]);

  const contentLineRows = useMemo(() => {
    if (versionDiff?.content_diff?.mode !== 'text_lines') {
      return [];
    }
    return Array.isArray(versionDiff.content_diff.changes) ? versionDiff.content_diff.changes : [];
  }, [versionDiff]);

  const canJumpToBacktestCompare = Boolean(versionDiff?.backtest_compare?.compare_ready);

  const handleJumpToBacktestCompare = () => {
    const compare = versionDiff?.backtest_compare;
    if (!compare?.compare_ready) {
      return;
    }
    const compareUrl = compare.compare_page_url || `/backtest?compareA=${compare.current_report_id}&compareB=${compare.baseline_report_id}`;
    window.location.href = compareUrl;
  };


  return (
    <div className="flex h-full flex-col bg-[#0a0a12] text-gray-300 font-mono">
      <div className="flex items-center justify-between border-b border-border bg-bg-card/50 p-4">
        <PageTitle title="演进中心" subtitle="策略版本演进、回测归档与 OODA 复盘" />
        <div className="flex items-center gap-4">
          <div className="flex bg-black/50 border border-border rounded overflow-hidden p-0.5">
            {TABS.map((tab) => (
              <button
                key={tab.value}
                onClick={() => setActiveTab(tab.value)}
                className={cn(
                  'px-4 py-1 text-[10px] font-bold uppercase transition-all',
                  activeTab === tab.value ? 'bg-neon-cyan/20 text-neon-cyan' : 'text-info-gray hover:text-white',
                )}
              >
                {tab.label}
              </button>
            ))}
          </div>
          <button onClick={() => void fetchData()} className="p-2 border border-border rounded hover:border-neon-cyan transition-all">
            <RefreshCw className={cn('h-4 w-4', loading && 'animate-spin')} />
          </button>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        <div className="w-[300px] border-r border-border bg-bg-card/20 overflow-y-auto custom-scrollbar">
          <div className="p-3 bg-bg-card/50 border-b border-border">
            <div className="relative">
              <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-info-gray" />
              <input
                type="text"
                placeholder="Search strategy..."
                value={searchKeyword}
                onChange={(event) => setSearchKeyword(event.target.value)}
                className="w-full bg-black/50 border border-border rounded-full py-1 pl-7 pr-3 text-[10px] focus:border-neon-cyan outline-none"
              />
            </div>
          </div>

          <div className="divide-y divide-border/30">
            {loading && filteredStrategies.length === 0 ? (
              <div className="p-10 flex justify-center"><Loader2 className="h-6 w-6 animate-spin text-neon-cyan" /></div>
            ) : filteredStrategies.length === 0 ? (
              <div className="p-6 text-center text-info-gray text-xs">No matched strategy</div>
            ) : (
              filteredStrategies.map((strategy) => {
                const qualityPercent = strategy.quality === null ? null : strategy.quality * 100;
                return (
                  <div
                    key={strategy.id}
                    onClick={() => setSelectedId(strategy.id)}
                    className={cn(
                      'p-4 cursor-pointer transition-all border-l-2',
                      selectedId === strategy.id ? 'bg-neon-cyan/5 border-l-neon-cyan' : 'border-l-transparent hover:bg-white/5',
                    )}
                  >
                    <div className="flex justify-between items-start mb-1">
                      <span className="text-xs font-bold text-white uppercase truncate pr-2">{strategy.name}</span>
                      <span className="text-[9px] font-mono text-info-gray">{formatVersionLabel(strategy.version)}</span>
                    </div>
                    <div className="flex items-center gap-2 mb-3">
                      <span className={cn('text-[8px] font-bold px-1.5 py-0.5 rounded-sm border', typeColorClass(strategy.type))}>
                        {strategy.type}
                      </span>
                      <div className="flex-1 h-1 bg-gray-800 rounded-full overflow-hidden">
                        <div
                          className={cn('h-full', qualityPercent === null ? 'bg-info-gray/35' : 'bg-neon-cyan')}
                          style={{ width: `${qualityPercent ?? 0}%` }}
                        />
                      </div>
                      <span className={cn('text-[9px]', qualityPercent === null ? 'text-info-gray/60' : 'text-neon-cyan')}>
                        {qualityPercent === null ? '--' : `${qualityPercent.toFixed(0)}%`}
                      </span>
                    </div>
                    <MiniSparkline
                      data={strategy.returns}
                      color={strategy.quality !== null && strategy.quality > 0.8 ? '#00FF9D' : '#00f0ff'}
                    />
                  </div>
                );
              })
            )}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto custom-scrollbar bg-black/20 relative">
          {loading && <div className="absolute inset-0 bg-black/20 backdrop-blur-[1px] z-10" />}
          <div className="p-6">
            {activeTab === 'Overview' && (
              <div className="space-y-8 animate-in fade-in duration-500">
                <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
                  <StatCard icon={<Layers />} label="策略总量" value={strategies.length.toString()} />
                  <StatCard
                    icon={<Activity />}
                    label="活跃集群"
                    value={strategies.filter((strategy) => strategy.status === 'ACTIVE').length.toString()}
                  />
                  <StatCard icon={<GitBranch />} label="演进代数" value={evolutionDepth.toString()} color="text-neon-magenta" />
                  <StatCard
                    icon={<Zap />}
                    label="今日演进"
                    value={todayEvolutionCount.toString()}
                    color="text-warn-gold"
                  />
                  <StatCard
                    icon={<Target />}
                    label="捕获模式"
                    value={strategies.filter((strategy) => strategy.type === 'CAPTURED').length.toString()}
                    color="text-up-green"
                  />
                  <StatCard icon={<Shield />} label="合规等级" value={complianceRateText} color="text-neon-cyan" />
                </div>

                <div className="space-y-4">
                  <h3 className="text-xs font-bold text-white flex items-center gap-2 tracking-widest uppercase">
                    <History className="h-4 w-4 text-neon-cyan" /> Recent Evolution Events
                  </h3>
                  {events.length === 0 ? (
                    <div className="border border-border rounded bg-bg-card/30 p-4 text-xs text-info-gray">No evolution events.</div>
                  ) : (
                    <div className="space-y-3">
                      {events.map((event) => (
                        <div key={event.id} className="group relative pl-6 border-l border-border/50 py-1 hover:border-neon-cyan transition-colors">
                          <div className="absolute left-[-4.5px] top-2 h-2 w-2 rounded-full bg-border group-hover:bg-neon-cyan shadow-[0_0_8px_rgba(0,240,255,0.5)] transition-all" />
                          <div className="flex items-center gap-3 mb-1">
                            <span className="text-[10px] font-mono text-info-gray/60">{formatLocalTime(event.timestamp)}</span>
                            <span
                              className={cn(
                                'text-[9px] font-bold px-1 rounded-sm uppercase',
                                eventTypeBadgeClass(event.type),
                              )}
                            >
                              {event.type}
                            </span>
                            <span className="text-[10px] font-bold text-white uppercase">{event.strategyName}</span>
                          </div>
                          <p className="text-[11px] text-info-gray/80 leading-relaxed">{event.message}</p>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}

            {activeTab === 'Tree' && (
              <div className="space-y-3">
                {rootStrategies.length === 0 ? (
                  <div className="border border-border rounded bg-bg-card/30 p-4 text-xs text-info-gray">No lineage data.</div>
                ) : (
                  rootStrategies.map((root) => (
                    <TreeNode
                      key={root.id}
                      node={root}
                      level={0}
                      selectedId={selectedId}
                      childrenByParent={childrenByParent}
                      onSelect={(id) => setSelectedId(id)}
                    />
                  ))
                )}
              </div>
            )}

            {activeTab === 'OODA' && (
              <div className="space-y-4">
                {oodaLogs.length === 0 ? (
                  <div className="border border-border rounded bg-bg-card/30 p-4 text-xs text-info-gray">No OODA logs.</div>
                ) : (
                  oodaLogs.map((log) => (
                    <div key={log.id} className="bg-bg-card/40 border border-border rounded p-4 hover:border-neon-cyan/30 transition-all">
                      <div className="flex justify-between items-center mb-4 border-b border-border/30 pb-2">
                        <div className="flex items-center gap-3">
                          <span className="font-orbitron text-xs font-bold text-white">{log.date}</span>
                          <span className="text-[10px] text-info-gray uppercase">OODA #{log.id}</span>
                        </div>
                        <div className="flex gap-4">
                          <div className="flex flex-col items-end">
                            <span className="text-[9px] text-info-gray/50 uppercase">Trades</span>
                            <span className={cn('text-xs font-bold', log.trades === null ? 'text-info-gray/60' : 'text-white')}>
                              {log.trades === null ? '--' : log.trades}
                            </span>
                          </div>
                          <div className="flex flex-col items-end">
                            <span className="text-[9px] text-info-gray/50 uppercase">PnL</span>
                            <span className={cn('text-xs font-bold', log.pnl === null ? 'text-info-gray/60' : log.pnl >= 0 ? 'text-up-green' : 'text-down-red')}>
                              {log.pnl === null ? '--' : `¥${log.pnl.toFixed(2)}`}
                            </span>
                          </div>
                        </div>
                      </div>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <div className="space-y-3">
                          <OODAPhase label="Observe" text={log.observe} icon={<Eye />} color="text-neon-cyan" />
                          <OODAPhase label="Orient" text={log.orient} icon={<Crosshair />} color="text-warn-gold" />
                        </div>
                        <div className="space-y-3">
                          <OODAPhase label="Decide" text={log.decide} icon={<Target />} color="text-neon-magenta" />
                          <OODAPhase label="Act" text={log.act} icon={<Zap />} color="text-up-green" />
                        </div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            )}

            {activeTab === 'Comparison' && (
              <div className="border border-border rounded bg-bg-card/30 overflow-hidden">
                <table className="w-full text-xs">
                  <thead className="bg-bg-card/80 border-b border-border">
                    <tr className="text-info-gray uppercase tracking-wide text-[10px]">
                      <th className="px-4 py-3 text-left">Strategy</th>
                      <th className="px-4 py-3 text-right">Quality</th>
                      <th className="px-4 py-3 text-right">Win Rate</th>
                      <th className="px-4 py-3 text-right">Sharpe</th>
                      <th className="px-4 py-3 text-right">Max DD</th>
                      <th className="px-4 py-3 text-right">Net PnL</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/40">
                    {comparisonStrategies.map((strategy) => (
                      <tr key={strategy.id} className="hover:bg-bg-card/40 cursor-pointer" onClick={() => setSelectedId(strategy.id)}>
                        <td className="px-4 py-3">
                          <div className="flex flex-col">
                            <span className="text-white font-semibold uppercase">{strategy.name}</span>
                            <span className="text-[10px] text-info-gray/70">{formatVersionLabel(strategy.version)} · {strategy.type}</span>
                          </div>
                        </td>
                        <td className={cn('px-4 py-3 text-right', strategy.quality === null ? 'text-info-gray/60' : 'text-neon-cyan')}>
                          {strategy.quality === null ? '--' : `${(strategy.quality * 100).toFixed(1)}%`}
                        </td>
                        <td className={cn('px-4 py-3 text-right', strategy.winRate === null ? 'text-info-gray/60' : 'text-white')}>
                          {formatPercent(strategy.winRate, 1)}
                        </td>
                        <td className={cn('px-4 py-3 text-right', strategy.sharpe === null ? 'text-info-gray/60' : 'text-white')}>
                          {formatDecimal(strategy.sharpe, 2)}
                        </td>
                        <td className={cn('px-4 py-3 text-right', strategy.maxDrawdown === null ? 'text-info-gray/60' : 'text-warn-gold')}>
                          {formatPercent(strategy.maxDrawdown, 2)}
                        </td>
                        <td
                          className={cn(
                            'px-4 py-3 text-right font-semibold',
                            strategy.netPnl === null ? 'text-info-gray/60' : strategy.netPnl >= 0 ? 'text-up-green' : 'text-down-red',
                          )}
                        >
                          {formatDecimal(strategy.netPnl, 2)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {comparisonStrategies.length === 0 && (
                  <div className="p-4 text-xs text-info-gray">No strategy to compare.</div>
                )}
              </div>
            )}
          </div>
        </div>

        {selectedStrategy && (
          <div className="w-[320px] border-l border-border bg-bg-card/30 p-4 space-y-6">
            <h4 className="text-xs font-bold text-white flex items-center gap-2 uppercase tracking-widest border-b border-border pb-3">
              <Info className="h-3.5 w-3.5 text-neon-cyan" /> Details
            </h4>
            <div className="space-y-4">
              <div>
                <label className="text-[9px] text-info-gray uppercase mb-1 block">Description</label>
                <p className="text-[11px] text-info-gray/80 leading-relaxed italic">{selectedStrategy.description}</p>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <Metric label="Win Rate" value={formatPercent(selectedStrategy.winRate, 1)} />
                <Metric label="Sharpe" value={formatDecimal(selectedStrategy.sharpe, 2)} />
                <Metric label="Max DD" value={formatPercent(selectedStrategy.maxDrawdown, 1)} />
                <Metric label="Created" value={formatLocalDate(selectedStrategy.createdAt)} />
                <Metric label="Trades" value={selectedStrategy.tradeCount === null ? '--' : selectedStrategy.tradeCount.toString()} />
                <Metric label="Net PnL" value={formatDecimal(selectedStrategy.netPnl, 2)} />
              </div>
              <div className="pt-4 space-y-2">
                <button
                  onClick={handleOpenBacktest}
                  disabled={!selectedStrategy.latestBacktestId}
                  className="w-full py-2 bg-neon-cyan/10 border border-neon-cyan/50 text-neon-cyan text-[10px] font-bold uppercase rounded-sm hover:bg-neon-cyan/20 flex items-center justify-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  <Play className="h-3 w-3" /> Open Backtest Report
                </button>
                <button
                  onClick={() => void handleLoadVersionDiff()}
                  disabled={diffLoading}
                  className="w-full py-2 bg-white/5 border border-border text-white text-[10px] font-bold uppercase rounded-sm hover:border-neon-cyan/40 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
                >
                  {diffLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : <GitBranch className="h-3 w-3" />} Version Diff
                </button>
                {diffError && <div className="text-[10px] text-down-red border border-down-red/40 rounded p-2">{diffError}</div>}
                {versionDiff && (
                  <div className="border border-border/70 rounded p-3 space-y-3 bg-bg-primary/30">
                    <div className="text-[10px] text-info-gray/70">
                      Baseline:
                      {' '}
                      {versionDiff.has_baseline && versionDiff.baseline
                        ? `${versionDiff.baseline.name} v${versionDiff.baseline.version} (${versionDiff.baseline_source})`
                        : 'N/A'}
                    </div>
                    <div className="grid grid-cols-1 gap-1 text-[10px]">
                      {diffMetricRows.map(([metricName, metric]) => (
                        <div key={metricName} className="flex items-center justify-between">
                          <span className="text-info-gray/70 uppercase">{metricName}</span>
                          <span className={cn(metric.delta >= 0 ? 'text-up-green' : 'text-down-red')}>
                            {metric.delta >= 0 ? '+' : ''}
                            {metric.delta.toFixed(4)}
                          </span>
                        </div>
                      ))}
                    </div>
                    <div className="text-[10px] text-info-gray/70">
                      Params:
                      {' '}
                      +{versionDiff.parameter_diff.added.length} / -{versionDiff.parameter_diff.removed.length} / ~
                      {versionDiff.parameter_diff.changed.length}
                    </div>
                    <div className="text-[10px] text-info-gray/70">
                      Content Changed:
                      {' '}
                      <span className={versionDiff.content_changed ? 'text-warn-gold' : 'text-up-green'}>
                        {versionDiff.content_changed ? 'YES' : 'NO'}
                      </span>
                    </div>
                    <div className="pt-2 border-t border-border/40 space-y-2">
                      <div className="text-[10px] text-info-gray/70 uppercase">Content Diff</div>
                      {versionDiff.content_diff?.mode === 'json_fields' ? (
                        contentFieldRows.length === 0 ? (
                          <div className="text-[10px] text-info-gray/50">No content field changes.</div>
                        ) : (
                          <div className="space-y-2 max-h-44 overflow-auto custom-scrollbar pr-1">
                            {contentFieldRows.map((row, index) => (
                              <div key={`${row.field}-${index}`} className="border border-border/40 rounded p-2 text-[10px] space-y-1">
                                <div className="flex items-center justify-between">
                                  <span className="text-neon-cyan">{row.field}</span>
                                  <span
                                    className={cn(
                                      'uppercase',
                                      row.status === 'added'
                                        ? 'text-up-green'
                                        : row.status === 'removed'
                                          ? 'text-down-red'
                                          : 'text-warn-gold',
                                    )}
                                  >
                                    {row.status}
                                  </span>
                                </div>
                                <div className="text-info-gray/60">baseline: {row.baseline_value || '--'}</div>
                                <div className="text-white">current: {row.current_value || '--'}</div>
                              </div>
                            ))}
                          </div>
                        )
                      ) : contentLineRows.length === 0 ? (
                        <div className="text-[10px] text-info-gray/50">No text line changes.</div>
                      ) : (
                        <div className="space-y-2 max-h-44 overflow-auto custom-scrollbar pr-1">
                          {contentLineRows.map((row, index) => (
                            <div key={`${row.type}-${index}`} className="border border-border/40 rounded p-2 text-[10px] space-y-1">
                              <div className="flex items-center justify-between">
                                <span className="text-info-gray/70">
                                  B[{row.baseline_range[0]}-{row.baseline_range[1]}] / C[{row.current_range[0]}-{row.current_range[1]}]
                                </span>
                                <span className="uppercase text-warn-gold">{row.type}</span>
                              </div>
                              {row.baseline_lines.length > 0 && (
                                <div className="text-down-red/90">- {row.baseline_lines.join(' / ')}</div>
                              )}
                              {row.current_lines.length > 0 && (
                                <div className="text-up-green/90">+ {row.current_lines.join(' / ')}</div>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                    <button
                      onClick={handleJumpToBacktestCompare}
                      disabled={!canJumpToBacktestCompare}
                      className="w-full py-2 bg-neon-magenta/10 border border-neon-magenta/40 text-neon-magenta text-[10px] font-bold uppercase rounded-sm hover:bg-neon-magenta/20 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      一键跳转回测报告对比
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

const TreeNode: FC<{
  node: Strategy;
  level: number;
  selectedId: string | null;
  childrenByParent: Map<string, Strategy[]>;
  onSelect: (id: string) => void;
}> = ({ node, level, selectedId, childrenByParent, onSelect }) => {
  const children = childrenByParent.get(node.id) ?? [];

  return (
    <div className="space-y-2">
      <div
        onClick={() => onSelect(node.id)}
        className={cn(
          'border rounded p-3 cursor-pointer transition-all',
          selectedId === node.id ? 'border-neon-cyan bg-neon-cyan/10' : 'border-border bg-bg-card/30 hover:border-neon-cyan/40',
        )}
        style={{ marginLeft: `${level * 20}px` }}
      >
        <div className="flex items-center justify-between gap-3">
          <div className="flex flex-col">
            <span className="text-white text-xs font-semibold uppercase">{node.name}</span>
            <span className="text-[10px] text-info-gray/70">{formatVersionLabel(node.version)} · {node.type}</span>
          </div>
          <span className={cn('text-[10px]', node.quality === null ? 'text-info-gray/60' : 'text-neon-cyan')}>
            {node.quality === null ? '--' : `${(node.quality * 100).toFixed(0)}%`}
          </span>
        </div>
      </div>
      {children.map((child) => (
        <TreeNode
          key={child.id}
          node={child}
          level={level + 1}
          selectedId={selectedId}
          childrenByParent={childrenByParent}
          onSelect={onSelect}
        />
      ))}
    </div>
  );
};

const StatCard: FC<{ icon: JSX.Element; label: string; value: string; color?: string }> = ({ icon, label, value, color = 'text-white' }) => (
  <div className="bg-bg-card border border-border rounded p-3 flex flex-col gap-1 group hover:border-neon-cyan/30 transition-all">
    <div className="flex items-center gap-2 text-info-gray/60 group-hover:text-neon-cyan transition-colors">
      {cloneElement(icon, { className: 'h-3.5 w-3.5' })}
      <span className="text-[9px] font-bold uppercase tracking-tighter">{label}</span>
    </div>
    <span className={cn('text-lg font-orbitron font-bold', color)}>{value}</span>
  </div>
);

const OODAPhase: FC<{ label: string; text: string; icon: JSX.Element; color: string }> = ({ label, text, icon, color }) => (
  <div className="space-y-1">
    <label className={cn('text-[9px] font-bold uppercase flex items-center gap-1.5 tracking-widest', color)}>
      {cloneElement(icon, { className: 'h-3 w-3' })} {label}
    </label>
    <p className="text-[11px] text-info-gray/90 bg-bg-primary/50 p-2 border border-border/30 rounded-sm">{text}</p>
  </div>
);

const Metric: FC<{ label: string; value: string }> = ({ label, value }) => (
  <div>
    <label className="text-[9px] text-info-gray/60 uppercase block">{label}</label>
    <p className="text-xs text-white font-semibold">{value}</p>
  </div>
);

export default EvolutionCenter;
