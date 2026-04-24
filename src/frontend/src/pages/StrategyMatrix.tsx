import React, { useState, useMemo, useEffect, useCallback } from 'react';
import { Loader2, RefreshCcw } from 'lucide-react';
import { cn } from '../lib/utils';
import { strategyApi } from '../services/api';

type StrategyStatus = 'ACTIVE' | 'RETIRED' | 'EVOLVING' | 'CANDIDATE' | 'DRAFT' | 'REJECTED' | 'PAUSED';

interface Strategy {
  id: string;
  name: string;
  version: string;
  status: StrategyStatus;
  winRate: number | null;
  plRatio: number | null;
  maxDrawdown: number | null;
  sharpeRatio: number | null;
  latency: number | null;
  qualityScore: number | null;
  gatePassed: boolean | null;
}

const toNumber = (value: unknown): number | null => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

const toObject = (value: unknown): Record<string, unknown> => {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {};
};

const normalizeStatus = (value: unknown): StrategyStatus => {
  const raw = String(value ?? '').trim().toUpperCase();
  const map: Record<string, StrategyStatus> = {
    ACTIVE: 'ACTIVE',
    RETIRED: 'RETIRED',
    EVOLVING: 'EVOLVING',
    CANDIDATE: 'CANDIDATE',
    DRAFT: 'DRAFT',
    REJECTED: 'REJECTED',
    PAUSED: 'PAUSED',
  };
  return map[raw] ?? 'DRAFT';
};

const formatPercent = (value: number | null): string => {
  if (value === null) {
    return '--';
  }
  return `${(value * 100).toFixed(1)}%`;
};

const formatNumber = (value: number | null, digits = 2): string => {
  if (value === null) {
    return '--';
  }
  return value.toFixed(digits);
};

const RadarChart: React.FC<{ strategy: Strategy }> = ({ strategy }) => {
  const metricMap: Array<{ label: string; normalized: number | null }> = [
    { label: '胜率', normalized: strategy.winRate === null ? null : Math.max(0, Math.min(strategy.winRate, 1)) },
    { label: '盈亏比', normalized: strategy.plRatio === null ? null : Math.max(0, Math.min(strategy.plRatio / 5, 1)) },
    { label: '最大回撤', normalized: strategy.maxDrawdown === null ? null : 1 - Math.max(0, Math.min(strategy.maxDrawdown, 1)) },
    { label: '夏普', normalized: strategy.sharpeRatio === null ? null : Math.max(0, Math.min(strategy.sharpeRatio / 5, 1)) },
    { label: '延迟', normalized: strategy.latency === null ? null : 1 - Math.max(0, Math.min(strategy.latency, 500)) / 500 },
  ];

  const missing = metricMap.filter((item) => item.normalized === null).map((item) => item.label);
  if (missing.length > 0) {
    return (
      <div className="flex flex-col items-center bg-gray-900/50 p-4 border border-neon-cyan/30 rounded-lg shadow-[0_0_15px_rgba(0,255,255,0.1)]">
        <h3 className="text-neon-cyan font-orbitron mb-4 text-center">质量雷达: {strategy.name}</h3>
        <div className="w-full rounded border border-dashed border-border p-4 text-xs text-info-gray">
          指标不完整，暂不渲染雷达图。缺失字段：{missing.join('、')}
        </div>
      </div>
    );
  }

  const stats = metricMap.map((item) => item.normalized ?? 0);
  const labels = metricMap.map((item) => item.label);
  const centerX = 150;
  const centerY = 150;
  const radius = 100;
  const angleStep = (Math.PI * 2) / 5;

  const getPoints = () => {
    return stats.map((val, i) => {
      const angle = i * angleStep - Math.PI / 2;
      const x = centerX + Math.cos(angle) * radius * val;
      const y = centerY + Math.sin(angle) * radius * val;
      return `${x},${y}`;
    }).join(' ');
  };

  return (
    <div className="flex flex-col items-center bg-gray-900/50 p-4 border border-neon-cyan/30 rounded-lg shadow-[0_0_15px_rgba(0,255,255,0.1)]">
      <h3 className="text-neon-cyan font-orbitron mb-4 text-center">质量雷达: {strategy.name}</h3>
      <svg width="300" height="300" className="overflow-visible">
        {[0.2, 0.4, 0.6, 0.8, 1.0].map((level) => (
          <polygon
            key={level}
            points={stats.map((_, i) => {
              const angle = i * angleStep - Math.PI / 2;
              return `${centerX + Math.cos(angle) * radius * level},${centerY + Math.sin(angle) * radius * level}`;
            }).join(' ')}
            fill="none"
            stroke="rgba(0,255,255,0.1)"
            strokeWidth="1"
          />
        ))}
        {labels.map((label, i) => {
          const angle = i * angleStep - Math.PI / 2;
          const x2 = centerX + Math.cos(angle) * radius;
          const y2 = centerY + Math.sin(angle) * radius;
          const lx = centerX + Math.cos(angle) * (radius + 20);
          const ly = centerY + Math.sin(angle) * (radius + 20);
          return (
            <g key={label}>
              <line x1={centerX} y1={centerY} x2={x2} y2={y2} stroke="rgba(0,255,255,0.2)" strokeWidth="1" />
              <text x={lx} y={ly} textAnchor="middle" className="fill-gray-400 text-[10px]" dy=".3em">{label}</text>
            </g>
          );
        })}
        <polygon
          points={getPoints()}
          fill="rgba(0,255,255,0.4)"
          stroke="#00f3ff"
          strokeWidth="2"
          className="drop-shadow-[0_0_5px_rgba(0,255,255,0.5)]"
        />
        {stats.map((val, i) => {
          const angle = i * angleStep - Math.PI / 2;
          const x = centerX + Math.cos(angle) * radius * val;
          const y = centerY + Math.sin(angle) * radius * val;
          return <circle key={i} cx={x} cy={y} r="3" fill="#00f3ff" />;
        })}
      </svg>
    </div>
  );
};

export const StrategyMatrix: React.FC = () => {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [loading, setLoading] = useState(true);
  const [sortKey, setSortKey] = useState<keyof Strategy>('qualityScore');
  const [filterStatus, setFilterStatus] = useState<'ALL' | StrategyStatus>('ALL');
  const [search, setSearch] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [transitioningId, setTransitioningId] = useState<string>('');
  const [actionError, setActionError] = useState('');

  const fetchData = useCallback(async () => {
    setLoading(true);
    setActionError('');
    try {
      const payload = await strategyApi.getVersions<{ items?: Array<Record<string, unknown>> } | Array<Record<string, unknown>>>();
      const rawBody =
        payload && typeof payload === 'object' && 'data' in payload
          ? ((payload as { data?: { items?: Array<Record<string, unknown>> } | Array<Record<string, unknown>> }).data ?? [])
          : payload;
      const raw = Array.isArray(rawBody)
        ? rawBody
        : Array.isArray(rawBody?.items)
          ? rawBody.items
          : [];

      const mapped: Strategy[] = raw.map((row) => {
        const metrics = toObject(row.metrics);
        const versionGate = toObject(metrics.version_gate);
        const gatePassedRaw = versionGate.passed;
        const gatePassed = typeof gatePassedRaw === 'boolean' ? gatePassedRaw : null;
        return {
          id: String(row.id ?? ''),
          name: String(row.name ?? 'Unnamed Strategy'),
          version: `v${String(row.version ?? '0')}`,
          status: normalizeStatus(row.status),
          winRate: toNumber(metrics.win_rate),
          plRatio: toNumber(metrics.profit_loss_ratio),
          maxDrawdown: toNumber(metrics.max_drawdown),
          sharpeRatio: toNumber(metrics.sharpe_ratio ?? metrics.sharpe),
          latency: toNumber(metrics.avg_response_time),
          qualityScore: toNumber(metrics.quality_score),
          gatePassed,
        };
      });

      setStrategies(mapped.filter((item) => item.id));
      setSelectedId((current) => {
        if (current && mapped.some((strategy) => strategy.id === current)) {
          return current;
        }
        return mapped[0]?.id ?? null;
      });
    } catch (err) {
      console.warn('[StrategyMatrix] API fetch failed:', err);
      setStrategies([]);
      setSelectedId(null);
      setActionError(String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void fetchData(); }, [fetchData]);

  const sortedAndFilteredStrategies = useMemo(() => {
    const isAscendingSort = sortKey === 'maxDrawdown' || sortKey === 'latency';
    const toSortValue = (value: Strategy[keyof Strategy]): number => {
      if (typeof value === 'number') {
        return value;
      }
      if (value === null) {
        return isAscendingSort ? Number.POSITIVE_INFINITY : Number.NEGATIVE_INFINITY;
      }
      return 0;
    };

    return strategies
      .filter((item) => filterStatus === 'ALL' || item.status === filterStatus)
      .filter((item) => item.name.toLowerCase().includes(search.toLowerCase()))
      .sort((a, b) => {
        const valA = toSortValue(a[sortKey]);
        const valB = toSortValue(b[sortKey]);
        return isAscendingSort ? valA - valB : valB - valA;
      });
  }, [strategies, sortKey, filterStatus, search]);

  const selectedStrategy = strategies.find((item) => item.id === selectedId) || strategies[0];
  const candidates = strategies.filter((item) => item.qualityScore !== null && item.qualityScore < 0.4 && item.status !== 'RETIRED');

  const transitionStatus = useCallback(async (id: string, targetStatus: 'retired' | 'active') => {
    setTransitioningId(id);
    setActionError('');
    try {
      await strategyApi.transitionVersion(id, {
        target_status: targetStatus,
        operator: 'frontend.strategy_matrix',
        force: false,
      });
      await fetchData();
    } catch (err) {
      setActionError(String(err));
    } finally {
      setTransitioningId('');
    }
  }, [fetchData]);

  return (
    <div className="flex flex-col h-full bg-[#0a0a12] text-gray-300 p-6 space-y-6 font-mono">
      <div className="flex flex-wrap items-center justify-between gap-4 bg-gray-900/40 p-4 border border-gray-800 rounded-lg">
        <div className="flex items-center space-x-4">
          <label className="text-xs uppercase tracking-wider text-gray-500">排序方式:</label>
          <select
            value={sortKey}
            onChange={(e) => setSortKey(e.target.value as keyof Strategy)}
            className="bg-black border border-gray-700 rounded px-2 py-1 text-sm text-neon-cyan focus:border-neon-cyan outline-none"
          >
            <option value="qualityScore">质量评分</option>
            <option value="winRate">胜率</option>
            <option value="sharpeRatio">夏普比率</option>
            <option value="maxDrawdown">最大回撤</option>
            <option value="latency">延迟</option>
          </select>

          <label className="text-xs uppercase tracking-wider text-gray-500 ml-4">筛选:</label>
          <div className="flex bg-black/50 border border-gray-800 rounded overflow-hidden">
            {['ALL', 'ACTIVE', 'EVOLVING', 'RETIRED'].map((item) => (
              <button
                key={item}
                onClick={() => setFilterStatus(item as 'ALL' | StrategyStatus)}
                className={`px-3 py-1 text-xs transition-colors ${filterStatus === item ? 'bg-neon-cyan/20 text-neon-cyan' : 'hover:bg-gray-800'}`}
              >
                {item === 'ALL' ? '全部' : item === 'ACTIVE' ? '活跃' : item === 'EVOLVING' ? '演进中' : '退役'}
              </button>
            ))}
          </div>
          <button onClick={() => void fetchData()} className="p-1 hover:text-neon-cyan transition-colors">
            <RefreshCcw className={cn('h-4 w-4', loading && 'animate-spin')} />
          </button>
        </div>

        <div className="relative">
          <input
            type="text"
            placeholder="搜索策略..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="bg-black border border-gray-700 rounded-full px-4 py-1 pl-10 text-sm focus:border-neon-cyan outline-none w-64"
          />
          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-600">🔍</span>
        </div>
      </div>

      {actionError && (
        <div className="rounded border border-down-red/50 bg-down-red/10 p-3 text-xs text-down-red">
          操作失败：{actionError}
        </div>
      )}

      <div className="flex flex-1 gap-6 overflow-hidden">
        <div className="flex-1 bg-gray-900/40 border border-gray-800 rounded-lg overflow-hidden flex flex-col relative">
          {loading && <div className="absolute inset-0 bg-black/20 backdrop-blur-sm z-20 flex items-center justify-center"><Loader2 className="h-8 w-8 animate-spin text-neon-cyan" /></div>}
          <div className="overflow-auto scrollbar-thin scrollbar-thumb-gray-800 scrollbar-track-transparent">
            <table className="w-full text-left text-xs">
              <thead className="sticky top-0 bg-gray-900 border-b border-gray-800 text-gray-500 uppercase">
                <tr>
                  <th className="p-4">名称</th>
                  <th className="p-4">状态</th>
                  <th className="p-4">胜率</th>
                  <th className="p-4">盈亏比</th>
                  <th className="p-4">最大回撤</th>
                  <th className="p-4">夏普</th>
                  <th className="p-4">质量评分</th>
                </tr>
              </thead>
              <tbody>
                {sortedAndFilteredStrategies.map((item) => (
                  <tr
                    key={item.id}
                    onClick={() => setSelectedId(item.id)}
                    className={`border-b border-gray-800/50 cursor-pointer transition-colors ${selectedId === item.id ? 'bg-neon-cyan/5 border-l-2 border-l-neon-cyan' : 'hover:bg-white/5'}`}
                  >
                    <td className="p-4">
                      <div className="font-bold text-gray-200">{item.name}</div>
                      <div className="text-[10px] text-gray-600">{item.version}</div>
                    </td>
                    <td className="p-4">
                      <span className={`px-2 py-0.5 rounded-full text-[10px] border ${
                        item.status === 'ACTIVE' ? 'bg-green-500/10 text-green-400 border-green-500/30' :
                        item.status === 'EVOLVING' ? 'bg-blue-500/10 text-blue-400 border-blue-500/30' :
                        item.status === 'RETIRED' ? 'bg-gray-500/10 text-gray-400 border-gray-500/30' :
                        'bg-warn-gold/10 text-warn-gold border-warn-gold/30'
                      }`}>
                        {item.status}
                      </span>
                    </td>
                    <td className="p-4">{formatPercent(item.winRate)}</td>
                    <td className="p-4">{formatNumber(item.plRatio)}</td>
                    <td className="p-4 text-red-400">{item.maxDrawdown === null ? '--' : `${(item.maxDrawdown * 100).toFixed(1)}%`}</td>
                    <td className="p-4">{formatNumber(item.sharpeRatio)}</td>
                    <td className="p-4 w-32">
                      {item.qualityScore === null ? (
                        <span className="text-info-gray/60">--</span>
                      ) : (
                        <div className="flex items-center space-x-2">
                          <div className="flex-1 h-1.5 bg-gray-800 rounded-full overflow-hidden">
                            <div
                              className={`h-full transition-all duration-1000 ${
                                item.qualityScore > 0.7 ? 'bg-neon-cyan shadow-[0_0_8px_#00f3ff]' :
                                item.qualityScore > 0.4 ? 'bg-yellow-500' : 'bg-red-500 shadow-[0_0_8px_#ef4444]'
                              }`}
                              style={{ width: `${Math.max(0, Math.min(item.qualityScore, 1)) * 100}%` }}
                            />
                          </div>
                          <span className="text-[10px] min-w-[24px]">{item.qualityScore.toFixed(2)}</span>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
                {sortedAndFilteredStrategies.length === 0 && (
                  <tr>
                    <td colSpan={7} className="p-6 text-center text-info-gray/60">暂无匹配策略</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="w-80 flex flex-col space-y-4">
          {selectedStrategy ? (
            <>
              <RadarChart strategy={selectedStrategy} />
              <div className="flex-1 bg-gray-900/40 border border-gray-800 rounded-lg p-4 space-y-4 overflow-auto text-xs">
                <h4 className="font-orbitron text-gray-400 uppercase tracking-widest border-b border-gray-800 pb-2">技术洞察</h4>
                <div className="grid grid-cols-2 gap-4">
                  <div className="bg-black/40 p-2 rounded border border-gray-800">
                    <div className="text-gray-600 mb-1">执行延迟</div>
                    <div className={cn(
                      selectedStrategy.latency === null ? 'text-info-gray/60' : selectedStrategy.latency < 50 ? 'text-green-400' : 'text-yellow-400',
                    )}>
                      {selectedStrategy.latency === null ? '--' : `${selectedStrategy.latency}ms`}
                    </div>
                  </div>
                  <div className="bg-black/40 p-2 rounded border border-gray-800">
                    <div className="text-gray-600 mb-1">版本门禁</div>
                    <div className={cn(
                      selectedStrategy.gatePassed === null ? 'text-info-gray/60' : selectedStrategy.gatePassed ? 'text-up-green' : 'text-down-red',
                    )}>
                      {selectedStrategy.gatePassed === null ? '未评估' : selectedStrategy.gatePassed ? '通过' : '未通过'}
                    </div>
                  </div>
                </div>
                <div className="rounded border border-border/40 bg-black/40 p-3 space-y-1">
                  <div>胜率：{formatPercent(selectedStrategy.winRate)}</div>
                  <div>盈亏比：{formatNumber(selectedStrategy.plRatio)}</div>
                  <div>最大回撤：{selectedStrategy.maxDrawdown === null ? '--' : `${(selectedStrategy.maxDrawdown * 100).toFixed(2)}%`}</div>
                  <div>夏普：{formatNumber(selectedStrategy.sharpeRatio)}</div>
                  <div>质量：{formatNumber(selectedStrategy.qualityScore)}</div>
                </div>
              </div>
            </>
          ) : (
            <div className="flex-1 border border-border/30 border-dashed rounded-lg flex items-center justify-center text-info-gray/40">请选择一个策略</div>
          )}
        </div>
      </div>

      <div className="h-40 bg-red-900/5 border border-red-500/20 rounded-lg p-4 flex flex-col">
        <div className="flex items-center justify-between mb-2">
          <h4 className="text-xs font-orbitron text-red-400 uppercase">
            退役候选策略 (质量评分 &lt; 0.4)
          </h4>
          <span className="text-[10px] text-red-500/50 font-mono">真实状态迁移 API 已接入</span>
        </div>

        <div className="flex-1 flex gap-4 overflow-x-auto pb-2 scrollbar-thin scrollbar-thumb-red-500/20">
          {candidates.length > 0 ? candidates.map((item) => (
            <div key={item.id} className="min-w-[280px] bg-black/60 border border-red-500/30 rounded p-3 flex justify-between items-center group">
              <div>
                <div className="text-sm font-bold text-gray-300">{item.name}</div>
                <div className="text-xs text-red-500">质量: {item.qualityScore?.toFixed(2) ?? '--'}</div>
              </div>
              <div className="flex space-x-2">
                <button
                  onClick={() => void transitionStatus(item.id, 'retired')}
                  disabled={transitioningId === item.id}
                  className="px-3 py-1 bg-red-500/20 text-red-500 text-[10px] rounded border border-red-500/40 hover:bg-red-500 hover:text-white transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {transitioningId === item.id ? '处理中' : '退役'}
                </button>
                <button
                  onClick={() => void transitionStatus(item.id, 'active')}
                  disabled={transitioningId === item.id}
                  className="px-3 py-1 bg-gray-800 text-gray-400 text-[10px] rounded border border-gray-700 hover:bg-gray-700 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  保留
                </button>
              </div>
            </div>
          )) : (
            <div className="flex-1 flex items-center justify-center text-gray-600 text-xs italic">
              当前周期未检测到低绩效策略。
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default StrategyMatrix;
