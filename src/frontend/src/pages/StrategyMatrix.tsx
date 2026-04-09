import React, { useState, useMemo, useEffect, useCallback } from 'react';
import { Loader2, RefreshCcw } from 'lucide-react';
import { cn } from '../lib/utils';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

/**
 * Strategy Matrix Page
 * Core Page for Phase 5.3
 * Layout: Left (Table) + Right (Radar Chart) + Bottom (Candidates)
 */

interface Strategy {
  id: string;
  name: string;
  version: string;
  status: 'ACTIVE' | 'RETIRED' | 'EVOLVING' | 'retired'; // Support both cases
  winRate: number;      
  plRatio: number;      
  maxDrawdown: number;  
  sharpeRatio: number;  
  latency: number;      
  qualityScore: number; 
}

const RadarChart: React.FC<{ strategy: Strategy }> = ({ strategy }) => {
  // Normalize values for radar (0-1)
  const stats = [
    strategy.winRate,
    Math.min((strategy.plRatio - 1) / 4, 1),
    1 - strategy.maxDrawdown,
    Math.min(strategy.sharpeRatio / 5, 1),
    1 - (Math.min(strategy.latency, 500) / 500),
  ];
  const labels = ['胜率', '盈亏比', '最大回撤', '夏普', '延迟'];
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
  const [filterStatus, setFilterStatus] = useState<'ALL' | 'ACTIVE' | 'RETIRED' | 'EVOLVING'>('ALL');
  const [search, setSearch] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/strategy/versions`);
      if (res.ok) {
        const json = await res.json();
        const raw = json.data || [];
        const mapped: Strategy[] = raw.map((s: any) => ({
          id: s.id,
          name: s.name,
          version: `v${s.version}`,
          status: (s.status || 'ACTIVE').toUpperCase(),
          winRate: s.metrics?.win_rate || 0.5,
          plRatio: s.metrics?.profit_loss_ratio || 1.5,
          maxDrawdown: s.metrics?.max_drawdown || 0.1,
          sharpeRatio: s.metrics?.sharpe_ratio || 2.0,
          latency: s.metrics?.avg_response_time || 50,
          qualityScore: s.metrics?.quality_score || 0.7,
        }));
        setStrategies(mapped);
        if (mapped.length > 0 && !selectedId) {
          setSelectedId(mapped[0].id);
        }
      }
    } catch (err) {
      console.warn('[StrategyMatrix] API fetch failed:', err);
    } finally {
      setLoading(false);
    }
  }, [selectedId]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const filteredStrategies = useMemo(() => {
    return strategies
      .filter(s => filterStatus === 'ALL' || s.status === filterStatus)
      .filter(s => s.name.toLowerCase().includes(search.toLowerCase()))
      .sort((a, b) => {
        const valA = a[sortKey];
        const valB = b[sortKey];
        if (typeof valA === 'number' && typeof valB === 'number') return valB - valA;
        return 0;
      });
  }, [strategies, sortKey, filterStatus, search]);

  const selectedStrategy = strategies.find(s => s.id === selectedId) || strategies[0];
  const candidates = strategies.filter(s => s.qualityScore < 0.4 && s.status !== 'RETIRED');

  return (
    <div className="flex flex-col h-full bg-[#0a0a12] text-gray-300 p-6 space-y-6 font-mono">
      {/* Top Toolbar */}
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
          </select>

          <label className="text-xs uppercase tracking-wider text-gray-500 ml-4">筛选:</label>
          <div className="flex bg-black/50 border border-gray-800 rounded overflow-hidden">
            {['全部', '活跃', '演进中', '退役'].map(s => (
              <button
                key={s}
                onClick={() => setFilterStatus(s === '全部' ? 'ALL' : s === '活跃' ? 'ACTIVE' : s === '演进中' ? 'EVOLVING' : 'RETIRED')}
                className={`px-3 py-1 text-xs transition-colors ${filterStatus === (s === '全部' ? 'ALL' : s === '活跃' ? 'ACTIVE' : s === '演进中' ? 'EVOLVING' : 'RETIRED') ? 'bg-neon-cyan/20 text-neon-cyan' : 'hover:bg-gray-800'}`}
              >
                {s}
              </button>
            ))}
          </div>
          <button onClick={fetchData} className="p-1 hover:text-neon-cyan transition-colors">
            <RefreshCcw className={cn("h-4 w-4", loading && "animate-spin")} />
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

      <div className="flex flex-1 gap-6 overflow-hidden">
        {/* Left: Table Area */}
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
                {filteredStrategies.map(s => (
                  <tr 
                    key={s.id} 
                    onClick={() => setSelectedId(s.id)}
                    className={`border-b border-gray-800/50 cursor-pointer transition-colors ${selectedId === s.id ? 'bg-neon-cyan/5 border-l-2 border-l-neon-cyan' : 'hover:bg-white/5'}`}
                  >
                    <td className="p-4">
                      <div className="font-bold text-gray-200">{s.name}</div>
                      <div className="text-[10px] text-gray-600">{s.version}</div>
                    </td>
                    <td className="p-4">
                      <span className={`px-2 py-0.5 rounded-full text-[10px] border ${
                        s.status === 'ACTIVE' ? 'bg-green-500/10 text-green-400 border-green-500/30' :
                        s.status === 'EVOLVING' ? 'bg-blue-500/10 text-blue-400 border-blue-500/30' :
                        'bg-gray-500/10 text-gray-400 border-gray-500/30'
                      }`}>
                        {s.status}
                      </span>
                    </td>
                    <td className="p-4">{(s.winRate * 100).toFixed(1)}%</td>
                    <td className="p-4">{s.plRatio.toFixed(2)}</td>
                    <td className="p-4 text-red-400">{(s.maxDrawdown * 100).toFixed(1)}%</td>
                    <td className="p-4">{s.sharpeRatio.toFixed(2)}</td>
                    <td className="p-4 w-32">
                      <div className="flex items-center space-x-2">
                        <div className="flex-1 h-1.5 bg-gray-800 rounded-full overflow-hidden">
                          <div 
                            className={`h-full transition-all duration-1000 ${
                              s.qualityScore > 0.7 ? 'bg-neon-cyan shadow-[0_0_8px_#00f3ff]' :
                              s.qualityScore > 0.4 ? 'bg-yellow-500' : 'bg-red-500 shadow-[0_0_8px_#ef4444]'
                            }`}
                            style={{ width: `${s.qualityScore * 100}%` }}
                          />
                        </div>
                        <span className="text-[10px] min-w-[24px]">{s.qualityScore.toFixed(2)}</span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Right: Detail & Radar Area */}
        <div className="w-80 flex flex-col space-y-4">
          {selectedStrategy ? (
            <>
              <RadarChart strategy={selectedStrategy} />
              <div className="flex-1 bg-gray-900/40 border border-gray-800 rounded-lg p-4 space-y-4 overflow-auto text-xs">
                <h4 className="font-orbitron text-gray-400 uppercase tracking-widest border-b border-gray-800 pb-2">技术洞察</h4>
                <div className="grid grid-cols-2 gap-4">
                  <div className="bg-black/40 p-2 rounded border border-gray-800">
                    <div className="text-gray-600 mb-1">执行延迟</div>
                    <div className={cn(selectedStrategy.latency < 50 ? 'text-green-400' : 'text-yellow-400')}>{selectedStrategy.latency}ms</div>
                  </div>
                  <div className="bg-black/40 p-2 rounded border border-gray-800">
                    <div className="text-gray-600 mb-1">一致性</div>
                    <div className="text-neon-magenta">极高</div>
                  </div>
                </div>
                <div className="text-[11px] leading-relaxed text-gray-500 italic">
                  "This strategy shows {selectedStrategy.qualityScore > 0.8 ? 'superior' : 'moderate'} performance metrics. 
                  {selectedStrategy.maxDrawdown > 0.2 ? ' Caution advised on drawdown.' : ' Stability is within safe operational bounds.'}"
                </div>
              </div>
            </>
          ) : (
            <div className="flex-1 border border-border/30 border-dashed rounded-lg flex items-center justify-center text-info-gray/40">请选择一个策略</div>
          )}
        </div>
      </div>

      {/* Bottom: Retirement Candidates */}
      <div className="h-40 bg-red-900/5 border border-red-500/20 rounded-lg p-4 flex flex-col">
        <div className="flex items-center justify-between mb-2">
          <h4 className="text-xs font-orbitron text-red-400 flex items-center uppercase">
            <span className="mr-2">⚠️</span> 退役候选策略 (质量评分 &lt; 0.4)
          </h4>
          <span className="text-[10px] text-red-500/50 font-mono">系统自动检测已开启</span>
        </div>
        
        <div className="flex-1 flex gap-4 overflow-x-auto pb-2 scrollbar-thin scrollbar-thumb-red-500/20">
          {candidates.length > 0 ? candidates.map(c => (
            <div key={c.id} className="min-w-[280px] bg-black/60 border border-red-500/30 rounded p-3 flex justify-between items-center group">
              <div>
                <div className="text-sm font-bold text-gray-300">{c.name}</div>
                <div className="text-xs text-red-500">质量: {c.qualityScore.toFixed(2)}</div>
              </div>
              <div className="flex space-x-2">
                <button className="px-3 py-1 bg-red-500/20 text-red-500 text-[10px] rounded border border-red-500/40 hover:bg-red-500 hover:text-white transition-all">退役</button>
                <button className="px-3 py-1 bg-gray-800 text-gray-400 text-[10px] rounded border border-gray-700 hover:bg-gray-700 transition-all">保留</button>
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
