import { useState, useMemo, FC } from 'react';

/**
 * Memory Vault Page
 * Core Page for Phase 5.3
 * Layout: Left (Nav) + Middle (List) + Right (Detail)
 */

interface MemoryEntry {
  id: string;
  type: 'HOT' | 'WARM' | 'COLD';
  content: string;
  summary: string;
  tags: string[];
  importance: number; // 0-1
  createdAt: string;
  accessCount: number;
  lastAccess: string;
}

const MOCK_MEMORIES: MemoryEntry[] = [
  // HOT: 5 entries
  { id: 'M-H01', type: 'HOT', content: 'Agent "GigaTrend" reported anomalous slippage on BTC/USDT pair. Current execution path: Market -> Limit if slippage > 0.02%. Recommendation: Check provider latency.', summary: 'BTC Slippage Anomaly Detection', tags: ['BTC', 'EXECUTION'], importance: 0.95, createdAt: '2026-04-09 14:20', accessCount: 12, lastAccess: '2026-04-09 14:35' },
  { id: 'M-H02', type: 'HOT', content: 'Strategy "Alpha-X" stop-loss triggered at $68,200. Recovering state to Neutral. Awaiting next trend signal from Macro Monitor.', summary: 'Stop-Loss Triggered: Alpha-X', tags: ['BTC', 'STRATEGY'], importance: 0.88, createdAt: '2026-04-09 13:45', accessCount: 5, lastAccess: '2026-04-09 14:10' },
  { id: 'M-H03', type: 'HOT', content: 'Volatility spike detected in SOL/USDT. Level 2 Risk alert. Margin requirement increased by 5%.', summary: 'SOL Volatility Spike Alert', tags: ['SOL', 'RISK'], importance: 0.92, createdAt: '2026-04-09 15:05', accessCount: 8, lastAccess: '2026-04-09 15:15' },
  { id: 'M-H04', type: 'HOT', content: 'Websocket connection to Binance API re-established after 15ms dropout. State synchronized.', summary: 'API Re-connection Sync', tags: ['SYSTEM', 'API'], importance: 0.75, createdAt: '2026-04-09 14:50', accessCount: 3, lastAccess: '2026-04-09 15:00' },
  { id: 'M-H05', type: 'HOT', content: 'User requested manual override of ETH hedge position. Position reduced to 50% size.', summary: 'Manual Override: ETH Hedge', tags: ['MANUAL', 'ETH'], importance: 0.98, createdAt: '2026-04-09 15:20', accessCount: 20, lastAccess: '2026-04-09 15:30' },

  // WARM: 8 entries
  { id: 'M-W01', type: 'WARM', content: 'Moving average crossover on 4H chart for ETH. Bullish bias confirmed. Position sizing increased for next entry.', summary: 'ETH 4H Bullish Crossover', tags: ['ETH', 'TECHNICAL'], importance: 0.65, createdAt: '2026-04-08 22:00', accessCount: 45, lastAccess: '2026-04-09 09:30' },
  { id: 'M-W02', type: 'WARM', content: 'CPI data release led to 2% market-wide volatility. Strategy "GigaTrend" performed well, capturing +0.5% alpha.', summary: 'CPI Event Performance Review', tags: ['MACRO', 'PERFORMANCE'], importance: 0.72, createdAt: '2026-04-07 20:30', accessCount: 32, lastAccess: '2026-04-08 14:00' },
];

export const MemoryVault: FC = () => {
  const [activeTab, setActiveTab] = useState<'HOT' | 'WARM' | 'COLD'>('HOT');
  const [search, setSearch] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>('M-H01');

  const filteredMemories = useMemo(() => {
    return MOCK_MEMORIES.filter(m => m.type === activeTab && (m.summary.toLowerCase().includes(search.toLowerCase()) || m.content.toLowerCase().includes(search.toLowerCase())));
  }, [activeTab, search]);

  const selectedMemory = useMemo(() => {
    return MOCK_MEMORIES.find(m => m.id === selectedId) || MOCK_MEMORIES[0];
  }, [selectedId]);

  const handlePromote = (id: string) => {
    console.log('Promote:', id);
  };

  const handleDemote = (id: string) => {
    console.log('Demote:', id);
  };

  const handleForget = (id: string) => {
    console.log('Forget:', id);
  };

  return (
    <div className="flex h-[calc(100vh-80px)] w-full bg-[#0a0a0f] text-gray-400 font-mono overflow-hidden">
      {/* Left Dock: Type Selection */}
      <aside className="w-16 border-r border-gray-800 flex flex-col items-center py-6 space-y-8 bg-black/40">
        <button 
          onClick={() => setActiveTab('HOT')}
          className={`group relative p-3 rounded transition-all ${activeTab === 'HOT' ? 'text-neon-cyan shadow-[0_0_15px_rgba(0,255,255,0.2)]' : 'hover:text-gray-200'}`}
        >
          <div className={`text-[10px] font-bold tracking-tighter ${activeTab === 'HOT' ? 'opacity-100' : 'opacity-40'}`}>热记忆</div>
          {activeTab === 'HOT' && <div className="absolute -left-1 top-1/2 -translate-y-1/2 w-1 h-6 bg-neon-cyan" />}
        </button>
        <button 
          onClick={() => setActiveTab('WARM')}
          className={`group relative p-3 rounded transition-all ${activeTab === 'WARM' ? 'text-orange-400 shadow-[0_0_15px_rgba(251,146,60,0.2)]' : 'hover:text-gray-200'}`}
        >
          <div className={`text-[10px] font-bold tracking-tighter ${activeTab === 'WARM' ? 'opacity-100' : 'opacity-40'}`}>温记忆</div>
        </button>
        <button 
          onClick={() => setActiveTab('COLD')}
          className={`group relative p-3 rounded transition-all ${activeTab === 'COLD' ? 'text-blue-400 shadow-[0_0_15px_rgba(96,165,250,0.2)]' : 'hover:text-gray-200'}`}
        >
          <div className={`text-[10px] font-bold tracking-tighter ${activeTab === 'COLD' ? 'opacity-100' : 'opacity-40'}`}>冷记忆</div>
        </button>
      </aside>

      {/* Middle: Memory List */}
      <div className="w-[450px] border-r border-gray-800 flex flex-col bg-black/20">
        <div className="p-4 border-b border-gray-800">
          <div className="relative">
            <input 
              type="text" 
              placeholder="搜索记忆金库..." 
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full bg-black/60 border border-gray-800 rounded px-4 py-2 text-xs focus:border-neon-cyan outline-none transition-all placeholder:text-gray-700"
            />
            <div className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] text-gray-700">ESC</div>
          </div>
        </div>
        <div className="flex-1 overflow-auto custom-scrollbar">
          {filteredMemories.map((m) => (
            <div 
              key={m.id}
              onClick={() => setSelectedId(m.id)}
              className={`p-5 border-b border-gray-900 cursor-pointer transition-all ${selectedId === m.id ? 'bg-neon-cyan/5 border-l-2 border-l-neon-cyan' : 'hover:bg-gray-800/20'}`}
            >
              <div className="flex justify-between items-start mb-2">
                <span className="text-[10px] font-orbitron text-neon-cyan/60">{m.id}</span>
                <span className="text-[9px] text-gray-600">{m.createdAt}</span>
              </div>
              <h4 className="text-xs font-bold text-gray-200 mb-2 truncate uppercase">{m.summary}</h4>
              <div className="flex flex-wrap gap-2">
                {m.tags.map(tag => (
                  <span key={tag} className="text-[8px] px-1.5 py-0.5 border border-gray-800 rounded text-gray-500 uppercase">#{tag}</span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Right: Detailed View */}
      <div className="flex-1 flex flex-col relative">
        {/* Background Decorative Grid */}
        <div className="absolute inset-0 opacity-[0.02] pointer-events-none" style={{ backgroundImage: 'radial-gradient(#fff 1px, transparent 0)', backgroundSize: '24px 24px' }} />
        
        <div className="flex-1 p-10 flex flex-col z-10">
          <div className="max-w-3xl w-full mx-auto flex flex-col h-full">
            <div className="flex justify-between items-start mb-10 border-b border-gray-800 pb-6">
              <div>
                <div className="flex items-center gap-3 mb-2">
                  <span className={`px-2 py-0.5 rounded-sm text-[10px] font-bold ${activeTab === 'HOT' ? 'bg-neon-cyan/20 text-neon-cyan' : activeTab === 'WARM' ? 'bg-orange-500/20 text-orange-500' : 'bg-blue-500/20 text-blue-500'}`}>
                    {selectedMemory.type === 'HOT' ? '热' : selectedMemory.type === 'WARM' ? '温' : '冷'}记忆
                  </span>
                  <span className="text-xs text-gray-600">ID: {selectedMemory.id}</span>
                </div>
                <h2 className="text-2xl font-orbitron font-black text-white tracking-tighter uppercase leading-none">
                  {selectedMemory.summary}
                </h2>
              </div>
              <div className="text-right">
                <div className="text-[10px] text-gray-500 mb-1">重要度</div>
                <div className="text-sm text-neon-magenta">{(selectedMemory.importance * 100).toFixed(0)}%</div>
              </div>
            </div>

            <div className="flex-1 overflow-auto space-y-6 pr-2 scrollbar-thin scrollbar-thumb-gray-800">
              <section>
                <h5 className="text-[10px] text-gray-500 uppercase mb-2 tracking-widest font-orbitron">记忆固化内容</h5>
                <div className="p-4 bg-black/60 border border-gray-800 rounded text-xs leading-relaxed text-gray-400 whitespace-pre-wrap">
                  {selectedMemory.content}
                </div>
              </section>

              <section>
                <h5 className="text-[10px] text-gray-500 uppercase mb-2 tracking-widest font-orbitron">元数据索引</h5>
                <div className="grid grid-cols-2 gap-4">
                  <div className="bg-black/40 p-3 rounded border border-gray-800">
                    <div className="text-[9px] text-gray-600 mb-1 uppercase">创建于</div>
                    <div className="text-[10px]">{selectedMemory.createdAt}</div>
                  </div>
                  <div className="bg-black/40 p-3 rounded border border-gray-800">
                    <div className="text-[9px] text-gray-600 mb-1 uppercase">最后访问</div>
                    <div className="text-[10px]">{selectedMemory.lastAccess}</div>
                  </div>
                  <div className="bg-black/40 p-3 rounded border border-gray-800">
                    <div className="text-[9px] text-gray-600 mb-1 uppercase">访问次数</div>
                    <div className="text-[10px] text-neon-cyan">{selectedMemory.accessCount}</div>
                  </div>
                  <div className="bg-black/40 p-3 rounded border border-gray-800">
                    <div className="text-[9px] text-gray-600 mb-1 uppercase">生存周期状态</div>
                    <div className="text-[10px] text-green-400">Stable</div>
                  </div>
                </div>
              </section>
            </div>

            <div className="mt-8 grid grid-cols-2 gap-3 pt-4 border-t border-gray-800">
              <button 
                onClick={() => handlePromote(selectedMemory.id)}
                className="px-4 py-2 bg-neon-cyan/10 border border-neon-cyan/40 text-neon-cyan text-[10px] rounded hover:bg-neon-cyan/20 transition-all font-orbitron"
              >
                {selectedMemory.type === 'HOT' ? '永久固化' : '提升层级'}
              </button>
              <button 
                onClick={() => handleDemote(selectedMemory.id)}
                className="px-4 py-2 bg-neon-magenta/10 border border-neon-magenta/40 text-neon-magenta text-[10px] rounded hover:bg-neon-magenta/20 transition-all font-orbitron"
              >
                {selectedMemory.type === 'COLD' ? '激活还原' : '降低层级'}
              </button>
              <button 
                onClick={() => handleForget(selectedMemory.id)}
                className="col-span-2 px-4 py-2 bg-red-900/20 border border-red-900/40 text-red-500 text-[10px] rounded hover:bg-red-900/40 transition-all font-orbitron mt-2"
              >
                遗忘记忆 (从金库中擦除)
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default MemoryVault;
