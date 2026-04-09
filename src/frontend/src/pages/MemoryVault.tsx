import React, { useState, useMemo } from 'react';

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
  { id: 'M-W03', type: 'WARM', content: 'Re-balanced portfolio from DeFi focus to Layer-1 assets. Current ratio: 40/60.', summary: 'Portfolio Re-balancing', tags: ['PORTFOLIO'], importance: 0.58, createdAt: '2026-04-06 10:00', accessCount: 22, lastAccess: '2026-04-09 08:00' },
  { id: 'M-W04', type: 'WARM', content: 'Testing new RSI-based filter on Backtest Lab. Result: Improved Sharpe from 1.8 to 2.1.', summary: 'RSI Filter Backtest Result', tags: ['LAB', 'STRATEGY'], importance: 0.45, createdAt: '2026-04-05 16:20', accessCount: 15, lastAccess: '2026-04-07 11:45' },
  { id: 'M-W05', type: 'WARM', content: 'Identified correlation cluster between ARB and OP. Divergence noted.', summary: 'L2 Correlation Divergence', tags: ['CORRELATION', 'L2'], importance: 0.52, createdAt: '2026-04-04 14:00', accessCount: 18, lastAccess: '2026-04-06 15:30' },
  { id: 'M-W06', type: 'WARM', content: 'Audit log show frequent API rate limit warnings. Adjusted polling interval to 2s.', summary: 'API Rate Limit Optimization', tags: ['SYSTEM', 'AUDIT'], importance: 0.48, createdAt: '2026-04-03 11:00', accessCount: 10, lastAccess: '2026-04-05 09:00' },
  { id: 'M-W07', type: 'WARM', content: 'Market sentiment shifted to "Greed" index 75. Monitoring for reversal signs.', summary: 'Sentiment: Greed Shift', tags: ['MACRO', 'SENTIMENT'], importance: 0.60, createdAt: '2026-04-02 18:00', accessCount: 50, lastAccess: '2026-04-09 10:00' },
  { id: 'M-W08', type: 'WARM', content: 'Completed weekly risk audit. No critical vulnerabilities found.', summary: 'Weekly Risk Audit Complete', tags: ['RISK', 'AUDIT'], importance: 0.40, createdAt: '2026-04-01 09:00', accessCount: 8, lastAccess: '2026-04-03 14:00' },

  // COLD: 6 entries
  { id: 'M-C01', type: 'COLD', content: 'Historical analysis of 2024 halving event impact on mining difficulty and price correlation.', summary: '2024 Halving Analysis', tags: ['HISTORICAL', 'HALVING'], importance: 0.35, createdAt: '2025-12-15 12:00', accessCount: 120, lastAccess: '2026-03-20 15:00' },
  { id: 'M-C02', type: 'COLD', content: 'Long-term thesis on Decentralized AI and its role in automated trading infrastructure.', summary: 'DeAI Long-term Thesis', tags: ['THESIS', 'AI'], importance: 0.38, createdAt: '2025-11-20 10:00', accessCount: 85, lastAccess: '2026-04-01 11:00' },
  { id: 'M-C03', type: 'COLD', content: 'Lessons learned from the Liquidity Crunch of Jan 2026. Necessity of multi-venue execution.', summary: 'Post-Mortem: Jan 2026 Crunch', tags: ['LESSONS', 'LIQUIDITY'], importance: 0.42, createdAt: '2026-01-15 09:00', accessCount: 65, lastAccess: '2026-04-05 14:00' },
  { id: 'M-C04', type: 'COLD', content: 'Baseline Sharpe ratio distribution across all tested strategies in Phase 3.', summary: 'Phase 3 Sharpe Baseline', tags: ['BENCHMARK'], importance: 0.25, createdAt: '2025-10-10 14:00', accessCount: 40, lastAccess: '2026-02-10 09:00' },
  { id: 'M-C05', type: 'COLD', content: 'Regulatory framework update for Singapore VASP license. Impact on future expansion.', summary: 'Regulatory Update: Singapore', tags: ['REGULATORY'], importance: 0.30, createdAt: '2025-09-05 11:00', accessCount: 30, lastAccess: '2026-01-20 16:00' },
  { id: 'M-C06', type: 'COLD', content: 'Macro cycle theory: 4-year cycle validation and adjusted expectations for 2027.', summary: 'Macro Cycle Theory v2', tags: ['MACRO', 'THEORY'], importance: 0.32, createdAt: '2025-08-01 15:00', accessCount: 55, lastAccess: '2026-04-08 14:00' },
];

const MemoryVault: React.FC = () => {
  const [filterType, setFilterType] = useState<'ALL' | 'HOT' | 'WARM' | 'COLD'>('ALL');
  const [search, setSearch] = useState('');
  const [selectedId, setSelectedId] = useState(MOCK_MEMORIES[0].id);

  const filteredMemories = useMemo(() => {
    return MOCK_MEMORIES
      .filter(m => filterType === 'ALL' || m.type === filterType)
      .filter(m => 
        m.summary.toLowerCase().includes(search.toLowerCase()) || 
        m.content.toLowerCase().includes(search.toLowerCase()) ||
        m.tags.some(t => t.toLowerCase().includes(search.toLowerCase()))
      )
      .sort((a, b) => {
        // Hot first, then by importance
        if (a.type !== b.type) {
          const order = { HOT: 0, WARM: 1, COLD: 2 };
          return order[a.type] - order[b.type];
        }
        return b.importance - a.importance;
      });
  }, [filterType, search]);

  const selectedMemory = MOCK_MEMORIES.find(m => m.id === selectedId) || MOCK_MEMORIES[0];

  const typeStats = {
    HOT: MOCK_MEMORIES.filter(m => m.type === 'HOT').length,
    WARM: MOCK_MEMORIES.filter(m => m.type === 'WARM').length,
    COLD: MOCK_MEMORIES.filter(m => m.type === 'COLD').length,
  };

  return (
    <div className="flex flex-col h-full bg-[#0a0a12] text-gray-300 font-mono p-6">
      {/* Top Search Bar */}
      <div className="flex items-center space-x-6 bg-gray-900/40 p-4 border border-gray-800 rounded-lg mb-6">
        <div className="flex-1 relative">
          <input
            type="text"
            placeholder="Search within neural vault..."
            className="w-full bg-black/60 border border-gray-700 rounded-lg px-10 py-2 text-sm focus:border-neon-cyan outline-none"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-600">📡</span>
        </div>
        <div className="flex items-center space-x-2">
          {['ALL', 'HOT', 'WARM', 'COLD'].map(type => (
            <button
              key={type}
              onClick={() => setFilterType(type as any)}
              className={`px-4 py-1.5 text-xs rounded-full border transition-all ${
                filterType === type 
                ? 'bg-neon-cyan/20 border-neon-cyan text-neon-cyan shadow-[0_0_10px_rgba(0,255,255,0.2)]' 
                : 'bg-black/40 border-gray-800 hover:border-gray-600'
              }`}
            >
              {type}
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-1 gap-6 overflow-hidden">
        {/* Left: Type Navigation */}
        <div className="w-64 space-y-4 flex flex-col">
          <div 
            onClick={() => setFilterType('HOT')}
            className={`cursor-pointer p-4 rounded-lg border border-red-500/30 bg-gradient-to-br from-red-500/10 to-transparent transition-all hover:bg-red-500/20 ${filterType === 'HOT' ? 'border-red-500 ring-1 ring-red-500/50 shadow-[0_0_15px_rgba(239,68,68,0.2)]' : ''}`}
          >
            <div className="flex justify-between items-center mb-2">
              <span className="text-red-400 text-xs font-orbitron">HOT MEMORY</span>
              <span className="text-[10px] bg-red-500/20 text-red-500 px-1.5 rounded">{typeStats.HOT}/50</span>
            </div>
            <div className="text-[10px] text-gray-500 italic">Episodic Buffer (Immediate)</div>
            <div className="mt-3 h-1 bg-gray-800 rounded-full overflow-hidden">
              <div className="h-full bg-red-500 w-1/10" />
            </div>
          </div>

          <div 
            onClick={() => setFilterType('WARM')}
            className={`cursor-pointer p-4 rounded-lg border border-yellow-500/30 bg-gradient-to-br from-yellow-500/10 to-transparent transition-all hover:bg-yellow-500/20 ${filterType === 'WARM' ? 'border-yellow-500 ring-1 ring-yellow-500/50 shadow-[0_0_15px_rgba(234,179,8,0.2)]' : ''}`}
          >
            <div className="flex justify-between items-center mb-2">
              <span className="text-yellow-400 text-xs font-orbitron">WARM MEMORY</span>
              <span className="text-[10px] bg-yellow-500/20 text-yellow-500 px-1.5 rounded">{typeStats.WARM}/500</span>
            </div>
            <div className="text-[10px] text-gray-500 italic">Working Semantic (Weekly)</div>
            <div className="mt-3 h-1 bg-gray-800 rounded-full overflow-hidden">
              <div className="h-full bg-yellow-500 w-[1.6%]" />
            </div>
          </div>

          <div 
            onClick={() => setFilterType('COLD')}
            className={`cursor-pointer p-4 rounded-lg border border-blue-500/30 bg-gradient-to-br from-blue-500/10 to-transparent transition-all hover:bg-blue-500/20 ${filterType === 'COLD' ? 'border-blue-500 ring-1 ring-blue-500/50 shadow-[0_0_15px_rgba(59,130,246,0.2)]' : ''}`}
          >
            <div className="flex justify-between items-center mb-2">
              <span className="text-blue-400 text-xs font-orbitron">COLD MEMORY</span>
              <span className="text-[10px] bg-blue-500/20 text-blue-500 px-1.5 rounded">{typeStats.COLD}/∞</span>
            </div>
            <div className="text-[10px] text-gray-500 italic">Consolidated (Permanent)</div>
            <div className="mt-3 h-1 bg-gray-800 rounded-full overflow-hidden">
              <div className="h-full bg-blue-500 w-5%" />
            </div>
          </div>

          <div className="mt-auto p-4 bg-gray-900/40 border border-gray-800 rounded-lg">
            <h5 className="text-[10px] text-gray-500 uppercase mb-2 tracking-widest font-orbitron">Vault Status</h5>
            <div className="text-xs space-y-2">
              <div className="flex justify-between"><span>Indexing:</span> <span className="text-neon-cyan">Optimal</span></div>
              <div className="flex justify-between"><span>Latency:</span> <span className="text-green-400">2ms</span></div>
              <div className="flex justify-between"><span>Encryption:</span> <span className="text-gray-400">AES-256</span></div>
            </div>
          </div>
        </div>

        {/* Middle: Memory List */}
        <div className="flex-1 bg-gray-900/40 border border-gray-800 rounded-lg flex flex-col overflow-hidden">
          <div className="p-3 border-b border-gray-800 flex justify-between items-center">
            <span className="text-xs text-gray-500 font-orbitron">{filteredMemories.length} ENTRIES FOUND</span>
            <div className="flex space-x-2">
              <button className="p-1 hover:bg-gray-800 rounded">👁️</button>
              <button className="p-1 hover:bg-gray-800 rounded">🔄</button>
            </div>
          </div>
          <div className="flex-1 overflow-auto scrollbar-thin scrollbar-thumb-gray-800">
            {filteredMemories.map(m => (
              <div 
                key={m.id}
                onClick={() => setSelectedId(m.id)}
                className={`p-4 border-b border-gray-800 cursor-pointer transition-all hover:bg-white/5 ${selectedId === m.id ? 'bg-white/5 border-l-2 border-l-neon-cyan' : ''}`}
              >
                <div className="flex items-start justify-between mb-2">
                  <div className="flex items-center space-x-2">
                    <span className={`w-1.5 h-1.5 rounded-full ${
                      m.type === 'HOT' ? 'bg-red-500 shadow-[0_0_5px_#ef4444]' :
                      m.type === 'WARM' ? 'bg-yellow-500' : 'bg-blue-500'
                    }`} />
                    <span className="text-xs font-bold text-gray-200">{m.summary}</span>
                  </div>
                  <span className="text-[10px] text-gray-600 font-mono">{m.id}</span>
                </div>
                <p className="text-[11px] text-gray-500 line-clamp-2 mb-3 leading-relaxed">{m.content}</p>
                <div className="flex items-center justify-between">
                  <div className="flex space-x-1">
                    {m.tags.map(t => (
                      <span key={t} className="text-[9px] px-1.5 py-0.5 bg-gray-800 text-gray-400 rounded-sm border border-gray-700">#{t}</span>
                    ))}
                  </div>
                  <div className="w-20 h-1 bg-gray-800 rounded-full overflow-hidden">
                    <div className="h-full bg-neon-magenta shadow-[0_0_5px_#ff00ff]" style={{ width: `${m.importance * 100}%` }} />
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Right: Detail Panel */}
        <div className="w-96 flex flex-col space-y-4">
          <div className="bg-gray-900/60 border border-gray-800 rounded-lg p-6 flex flex-col h-full overflow-hidden">
            <div className="flex items-center justify-between mb-6 pb-4 border-b border-gray-800">
              <div>
                <h4 className="text-neon-cyan text-sm font-orbitron mb-1">MEM-DATA: {selectedMemory.id}</h4>
                <div className="text-[10px] text-gray-500 uppercase tracking-widest">Type: {selectedMemory.type} Storage</div>
              </div>
              <div className="text-right">
                <div className="text-[10px] text-gray-500 mb-1">RELEVANCE</div>
                <div className="text-sm text-neon-magenta">{(selectedMemory.importance * 100).toFixed(0)}%</div>
              </div>
            </div>

            <div className="flex-1 overflow-auto space-y-6 pr-2 scrollbar-thin scrollbar-thumb-gray-800">
              <section>
                <h5 className="text-[10px] text-gray-500 uppercase mb-2 tracking-widest font-orbitron">Consolidated Content</h5>
                <div className="p-4 bg-black/60 border border-gray-800 rounded text-xs leading-relaxed text-gray-400 whitespace-pre-wrap">
                  {selectedMemory.content}
                </div>
              </section>

              <section>
                <h5 className="text-[10px] text-gray-500 uppercase mb-2 tracking-widest font-orbitron">Metadata Index</h5>
                <div className="grid grid-cols-2 gap-4">
                  <div className="bg-black/40 p-3 rounded border border-gray-800">
                    <div className="text-[9px] text-gray-600 mb-1 uppercase">Created At</div>
                    <div className="text-[10px]">{selectedMemory.createdAt}</div>
                  </div>
                  <div className="bg-black/40 p-3 rounded border border-gray-800">
                    <div className="text-[9px] text-gray-600 mb-1 uppercase">Last Access</div>
                    <div className="text-[10px]">{selectedMemory.lastAccess}</div>
                  </div>
                  <div className="bg-black/40 p-3 rounded border border-gray-800">
                    <div className="text-[9px] text-gray-600 mb-1 uppercase">Access Count</div>
                    <div className="text-[10px] text-neon-cyan">{selectedMemory.accessCount}</div>
                  </div>
                  <div className="bg-black/40 p-3 rounded border border-gray-800">
                    <div className="text-[9px] text-gray-600 mb-1 uppercase">TTL Status</div>
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
                {selectedMemory.type === 'HOT' ? 'PERSIST' : 'PROMOTE'}
              </button>
              <button 
                onClick={() => handleDemote(selectedMemory.id)}
                className="px-4 py-2 bg-neon-magenta/10 border border-neon-magenta/40 text-neon-magenta text-[10px] rounded hover:bg-neon-magenta/20 transition-all font-orbitron"
              >
                {selectedMemory.type === 'COLD' ? 'RESTORE' : 'DEMOTE'}
              </button>
              <button 
                onClick={() => handleForget(selectedMemory.id)}
                className="col-span-2 px-4 py-2 bg-red-900/20 border border-red-900/40 text-red-500 text-[10px] rounded hover:bg-red-900/40 transition-all font-orbitron mt-2"
              >
                FORGET (ERASE FROM VAULT)
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default MemoryVault;
div>
                    <div className="text-[10px] text-green-400">Stable</div>
                  </div>
                </div>
              </section>
            </div>

            <div className="mt-8 grid grid-cols-2 gap-3 pt-4 border-t border-gray-800">
              <button className="px-4 py-2 bg-neon-cyan/10 border border-neon-cyan/40 text-neon-cyan text-[10px] rounded hover:bg-neon-cyan/20 transition-all font-orbitron">
                {selectedMemory.type === 'HOT' ? 'PERSIST' : 'PROMOTE'}
              </button>
              <button className="px-4 py-2 bg-neon-magenta/10 border border-neon-magenta/40 text-neon-magenta text-[10px] rounded hover:bg-neon-magenta/20 transition-all font-orbitron">
                {selectedMemory.type === 'COLD' ? 'RESTORE' : 'DEMOTE'}
              </button>
              <button className="col-span-2 px-4 py-2 bg-red-900/20 border border-red-900/40 text-red-500 text-[10px] rounded hover:bg-red-900/40 transition-all font-orbitron mt-2">
                FORGET (ERASE FROM VAULT)
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default MemoryVault;
