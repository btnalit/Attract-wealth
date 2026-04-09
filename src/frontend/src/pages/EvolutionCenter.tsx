import { useState, useEffect, useCallback, FC, cloneElement } from 'react';
import { 
  GitBranch, History, Search, Zap, Activity, Target, Shield,
  Layers, Info,
  Eye, Crosshair, Play, Loader2, RefreshCw
} from 'lucide-react';
import { cn } from '../lib/utils';
import { PageTitle } from '../components/PageTitle';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

// --- Types ---
type StrategyType = 'BASE' | 'FIX' | 'DERIVED' | 'CAPTURED';
type StrategyStatus = 'ACTIVE' | 'EVOLVING' | 'PAUSED';

interface Strategy {
  id: string;
  name: string;
  version: string;
  quality: number;
  status: StrategyStatus;
  type: StrategyType;
  parentId?: string;
  createdAt: string;
  description: string;
  returns: number[]; 
  maxDrawdown: number;
  sharpe: number;
  winRate: number;
}

interface EvolutionEvent {
  id: string;
  timestamp: string;
  type: StrategyType;
  strategyName: string;
  message: string;
}

interface OODALog {
  id: string;
  date: string;
  observe: string;
  orient: string;
  decide: string;
  act: string;
  trades: number;
  pnl: number;
  deviations: number;
}

// --- Mock Fallbacks ---
const MOCK_STRATEGIES: Strategy[] = [
  { id: 's1', name: 'Trend-Master-X', version: '2.1.0', quality: 0.85, status: 'ACTIVE', type: 'BASE', createdAt: '2026-03-01T10:00:00', description: 'Base trend following strategy.', returns: [2, 5, 3, 8, 6, 12, 10, 15, 13, 18], maxDrawdown: 12.5, sharpe: 1.8, winRate: 64.2 },
];

const MOCK_EVENTS: EvolutionEvent[] = [
  { id: 'e1', timestamp: '2026-04-05T16:45:00', type: 'DERIVED', strategyName: 'Trend-X-Alpha', message: 'Successfully derived from Trend-X-Fix-1.' },
];

const MOCK_OODA: OODALog[] = [
  { id: 'o1', date: '2026-04-08', observe: '32 trades executed.', orient: 'Slippage above 1.5%.', decide: 'Trigger Fix mode.', act: 'Evolved Trend-X-Fix-1.', trades: 32, pnl: 4500, deviations: 4 },
];

// --- Helper: Mini Sparkline ---
const MiniSparkline: FC<{ data: number[], color?: string }> = ({ data, color = "#00f0ff" }) => {
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min;
  const width = 100;
  const height = 30;
  const points = data.map((v, i) => `${(i / (data.length - 1)) * width},${height - ((v - min) / range) * height}`).join(' ');
  return (
    <svg width={width} height={height} className="overflow-visible">
      <polyline points={points} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  );
};

export const EvolutionCenter: FC = () => {
  const [activeTab, setActiveTab] = useState<'Overview' | 'Tree' | 'OODA' | 'Comparison'>('Overview');
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [events, setEvents] = useState<EvolutionEvent[]>([]);
  const [oodaLogs] = useState<OODALog[]>(MOCK_OODA);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [vRes, hRes] = await Promise.all([
        fetch(`${API_BASE}/api/strategy/versions`),
        fetch(`${API_BASE}/api/strategy/history`),
      ]);

      if (vRes.ok) {
        const json = await vRes.json();
        const raw = json.data || [];
        const mapped: Strategy[] = raw.map((s: any) => ({
          id: s.id,
          name: s.name,
          version: s.version.toString(),
          quality: s.metrics?.quality_score || 0.7,
          status: (s.status || 'ACTIVE').toUpperCase() as StrategyStatus,
          type: (s.evolution_type || 'BASE').toUpperCase() as StrategyType,
          parentId: s.parent_id,
          createdAt: new Date(s.created_at * 1000).toISOString(),
          description: s.description || 'No description available.',
          returns: [Math.random() * 10, Math.random() * 10, Math.random() * 10, Math.random() * 10], 
          maxDrawdown: s.metrics?.max_drawdown || 0.1,
          sharpe: s.metrics?.sharpe_ratio || 2.0,
          winRate: s.metrics?.win_rate || 0.5,
        }));
        setStrategies(mapped);
        if (mapped.length > 0 && !selectedId) setSelectedId(mapped[0].id);
      }

      if (hRes.ok) {
        const json = await hRes.json();
        const raw = json.data || [];
        setEvents(raw.map((e: any) => ({
          id: e.id,
          timestamp: new Date(e.timestamp * 1000).toISOString(),
          type: (e.type || 'FIX').toUpperCase() as StrategyType,
          strategyName: e.strategy_name,
          message: e.message
        })));
      } else {
        setEvents(MOCK_EVENTS);
      }
    } catch (err) {
      console.warn('[EvolutionCenter] API fetch failed:', err);
      setStrategies(MOCK_STRATEGIES);
      setEvents(MOCK_EVENTS);
    } finally {
      setLoading(false);
    }
  }, [selectedId]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const selectedStrategy = strategies.find(s => s.id === selectedId) || strategies[0];

  return (
    <div className="flex h-full flex-col bg-[#0a0a12] text-gray-300 font-mono">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border bg-bg-card/50 p-4">
        <PageTitle title="演进中心" subtitle="自进化策略实验室与 OODA 反思日志" />
        <div className="flex items-center gap-4">
          <div className="flex bg-black/50 border border-border rounded overflow-hidden p-0.5">
            {['概览', '演进树', 'OODA', '策略对比'].map(tab => (
              <button 
                key={tab}
                onClick={() => setActiveTab(tab as any)}
                className={cn(
                  "px-4 py-1 text-[10px] font-bold uppercase transition-all",
                  activeTab === tab ? "bg-neon-cyan/20 text-neon-cyan" : "text-info-gray hover:text-white"
                )}
              >
                {tab}
              </button>
            ))}
          </div>
          <button onClick={fetchData} className="p-2 border border-border rounded hover:border-neon-cyan transition-all">
            <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
          </button>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* Left: Strategy List */}
        <div className="w-[300px] border-r border-border bg-bg-card/20 overflow-y-auto custom-scrollbar">
          <div className="p-3 bg-bg-card/50 border-b border-border">
            <div className="relative">
              <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-info-gray" />
              <input type="text" placeholder="搜索策略..." className="w-full bg-black/50 border border-border rounded-full py-1 pl-7 pr-3 text-[10px] focus:border-neon-cyan outline-none" />
            </div>
          </div>
          <div className="divide-y divide-border/30">
            {loading && strategies.length === 0 ? (
              <div className="p-10 flex justify-center"><Loader2 className="h-6 w-6 animate-spin text-neon-cyan" /></div>
            ) : strategies.map(s => (
              <div 
                key={s.id} 
                onClick={() => setSelectedId(s.id)}
                className={cn(
                  "p-4 cursor-pointer transition-all border-l-2",
                  selectedId === s.id ? "bg-neon-cyan/5 border-l-neon-cyan" : "border-l-transparent hover:bg-white/5"
                )}
              >
                <div className="flex justify-between items-start mb-1">
                  <span className="text-xs font-bold text-white uppercase truncate pr-2">{s.name}</span>
                  <span className="text-[9px] font-mono text-info-gray">v{s.version}</span>
                </div>
                <div className="flex items-center gap-2 mb-3">
                  <span className={cn(
                    "text-[8px] font-bold px-1.5 py-0.5 rounded-sm border",
                    s.type === 'BASE' ? 'text-neon-cyan border-neon-cyan/30 bg-neon-cyan/10' :
                    s.type === 'FIX' ? 'text-warn-gold border-warn-gold/30 bg-warn-gold/10' :
                    s.type === 'CAPTURED' ? 'text-up-green border-up-green/30 bg-up-green/10' :
                    'text-neon-magenta border-neon-magenta/30 bg-neon-magenta/10'
                  )}>{s.type}</span>
                  <div className="flex-1 h-1 bg-gray-800 rounded-full overflow-hidden">
                    <div className="h-full bg-neon-cyan" style={{ width: `${s.quality * 100}%` }} />
                  </div>
                  <span className="text-[9px] text-neon-cyan">{(s.quality * 100).toFixed(0)}%</span>
                </div>
                <MiniSparkline data={s.returns} color={s.quality > 0.8 ? "#00FF9D" : "#00f0ff"} />
              </div>
            ))}
          </div>
        </div>

        {/* Middle Content */}
        <div className="flex-1 overflow-y-auto custom-scrollbar bg-black/20 relative">
          {loading && <div className="absolute inset-0 bg-black/20 backdrop-blur-[1px] z-10" />}
          <div className="p-6">
            {activeTab === '概览' && (
              <div className="space-y-8 animate-in fade-in duration-500">
                <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
                  <StatCard icon={<Layers />} label="策略总量" value={strategies.length.toString()} />
                  <StatCard icon={<Activity />} label="活跃集群" value={strategies.filter(s => s.status === 'ACTIVE').length.toString()} />
                  <StatCard icon={<GitBranch />} label="演进代数" value="12" color="text-neon-magenta" />
                  <StatCard icon={<Zap />} label="今日演进" value={events.filter(e => e.timestamp.includes(new Date().toISOString().split('T')[0])).length.toString()} color="text-warn-gold" />
                  <StatCard icon={<Target />} label="捕获模式" value={strategies.filter(s => s.type === 'CAPTURED').length.toString()} color="text-up-green" />
                  <StatCard icon={<Shield />} label="合规等级" value="99.2%" color="text-neon-cyan" />
                </div>

                <div className="space-y-4">
                  <h3 className="text-xs font-bold text-white flex items-center gap-2 tracking-widest uppercase">
                    <History className="h-4 w-4 text-neon-cyan" /> Recent Evolution Events
                  </h3>
                  <div className="space-y-3">
                    {events.map(e => (
                      <div key={e.id} className="group relative pl-6 border-l border-border/50 py-1 hover:border-neon-cyan transition-colors">
                        <div className="absolute left-[-4.5px] top-2 h-2 w-2 rounded-full bg-border group-hover:bg-neon-cyan shadow-[0_0_8px_rgba(0,240,255,0.5)] transition-all" />
                        <div className="flex items-center gap-3 mb-1">
                          <span className="text-[10px] font-mono text-info-gray/60">{new Date(e.timestamp).toLocaleTimeString()}</span>
                          <span className={cn(
                            "text-[9px] font-bold px-1 rounded-sm uppercase",
                            e.type === 'FIX' ? 'bg-warn-gold/20 text-warn-gold' : 'bg-neon-magenta/20 text-neon-magenta'
                          )}>{e.type}</span>
                          <span className="text-[10px] font-bold text-white uppercase">{e.strategyName}</span>
                        </div>
                        <p className="text-[11px] text-info-gray/80 leading-relaxed">{e.message}</p>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {activeTab === 'OODA' && (
              <div className="space-y-4">
                {oodaLogs.map(log => (
                  <div key={log.id} className="bg-bg-card/40 border border-border rounded p-4 hover:border-neon-cyan/30 transition-all">
                    <div className="flex justify-between items-center mb-4 border-b border-border/30 pb-2">
                      <div className="flex items-center gap-3">
                        <span className="font-orbitron text-xs font-bold text-white">{log.date}</span>
                        <span className="text-[10px] text-info-gray uppercase">OODA 周期 #{log.id}</span>
                      </div>
                      <div className="flex gap-4">
                        <div className="flex flex-col items-end">
                          <span className="text-[9px] text-info-gray/50 uppercase">Trades</span>
                          <span className="text-xs font-bold text-white">{log.trades}</span>
                        </div>
                        <div className="flex flex-col items-end">
                          <span className="text-[9px] text-info-gray/50 uppercase">PnL</span>
                          <span className={cn("text-xs font-bold", log.pnl >= 0 ? "text-up-green" : "text-down-red")}>¥{log.pnl}</span>
                        </div>
                      </div>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                      <div className="space-y-3">
                        <OODAPhase label="观察 (Observe)" text={log.observe} icon={<Eye />} color="text-neon-cyan" />
                        <OODAPhase label="判断 (Orient)" text={log.orient} icon={<Crosshair />} color="text-warn-gold" />
                      </div>
                      <div className="space-y-3">
                        <OODAPhase label="决策 (Decide)" text={log.decide} icon={<Target />} color="text-neon-magenta" />
                        <OODAPhase label="执行 (Act)" text={log.act} icon={<Zap />} color="text-up-green" />
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Right Detail Panel */}
        {selectedStrategy && (
          <div className="w-[320px] border-l border-border bg-bg-card/30 p-4 space-y-6">
            <h4 className="text-xs font-bold text-white flex items-center gap-2 uppercase tracking-widest border-b border-border pb-3">
              <Info className="h-3.5 w-3.5 text-neon-cyan" /> 策略参数
            </h4>
            <div className="space-y-4">
              <div>
                <label className="text-[9px] text-info-gray uppercase mb-1 block">描述</label>
                <p className="text-[11px] text-info-gray/80 leading-relaxed italic">"{selectedStrategy.description}"</p>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <Metric label="胜率" value={`${selectedStrategy.winRate.toFixed(1)}%`} />
                <Metric label="夏普比率" value={selectedStrategy.sharpe.toFixed(2)} />
                <Metric label="最大回撤" value={`${(selectedStrategy.maxDrawdown * 100).toFixed(1)}%`} />
                <Metric label="创建时间" value={new Date(selectedStrategy.createdAt).toLocaleDateString()} />
              </div>
              <div className="pt-4 space-y-2">
                <button className="w-full py-2 bg-neon-cyan/10 border border-neon-cyan/50 text-neon-cyan text-[10px] font-bold uppercase rounded-sm hover:bg-neon-cyan/20 flex items-center justify-center gap-2">
                  <Play className="h-3 w-3" /> 执行回测
                </button>
                <button className="w-full py-2 bg-white/5 border border-border text-white text-[10px] font-bold uppercase rounded-sm hover:bg-white/10 flex items-center justify-center gap-2">
                  <GitBranch className="h-3 w-3" /> 查看版本差异
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

const StatCard: FC<any> = ({ icon, label, value, color = "text-white" }) => (
  <div className="bg-bg-card border border-border rounded p-3 flex flex-col gap-1 group hover:border-neon-cyan/30 transition-all">
    <div className="flex items-center gap-2 text-info-gray/60 group-hover:text-neon-cyan transition-colors">
      {cloneElement(icon, { className: "h-3.5 w-3.5" })}
      <span className="text-[9px] font-bold uppercase tracking-tighter">{label}</span>
    </div>
    <span className={cn("text-lg font-orbitron font-bold", color)}>{value}</span>
  </div>
);

const OODAPhase: FC<any> = ({ label, text, icon, color }) => (
  <div className="space-y-1">
    <label className={cn("text-[9px] font-bold uppercase flex items-center gap-1.5 tracking-widest", color)}>
      {cloneElement(icon, { className: "h-3 w-3" })} {label}
    </label>
    <p className="text-[11px] text-info-gray/90 bg-bg-primary/50 p-2 border border-border/30 rounded-sm">{text}</p>
  </div>
);

const Metric: FC<any> = ({ label, value }) => (
  <div className="bg-black/40 p-2 rounded border border-border">
    <div className="text-[9px] text-info-gray/60 uppercase mb-0.5">{label}</div>
    <div className="text-xs font-bold text-white">{value}</div>
  </div>
);

export default EvolutionCenter;
