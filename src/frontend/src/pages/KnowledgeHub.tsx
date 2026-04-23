import React, { useState, useEffect } from 'react';
import { Search, BookOpen, Trash2, Save, BarChart2, Info, Loader2 } from 'lucide-react';
import { cn } from '../lib/utils';
import { strategyApi } from '../services/api';

interface KnowledgeItem {
  id: string;
  title: string;
  type: 'Pattern' | 'Lesson' | 'Rule';
  relevance: number;
  summary: string;
  tags: string[];
  fullContent: string;
  vector: [number, number]; // Simplified 2D projection
}

const mockKnowledge: KnowledgeItem[] = [
  {
    id: '1',
    title: 'Breakout Pattern (Bullish)',
    type: 'Pattern',
    relevance: 98,
    summary: 'Asset price breaks above a established resistance level with high volume.',
    tags: ['Breakout', 'Bullish', 'Volume'],
    fullContent: 'A bullish breakout occurs when the price breaks through a resistance level. This often signals the start of a new uptrend. Key confirmations include a significant increase in trading volume and a close above the resistance level.',
    vector: [0.8, 0.7]
  },
  {
    id: '2',
    title: 'Revenge Trading Risks',
    type: 'Lesson',
    relevance: 85,
    summary: 'The danger of attempting to recoup losses quickly through emotional trades.',
    tags: ['Psychology', 'Risk Management'],
    fullContent: 'Revenge trading is an emotional response to a loss where a trader attempts to "get it back" by taking larger, riskier positions. This almost always leads to further losses and capital depletion.',
    vector: [-0.6, -0.4]
  },
  {
    id: '3',
    title: 'Stop-Loss Rule (2%)',
    type: 'Rule',
    relevance: 100,
    summary: 'Never risk more than 2% of total capital on a single trade.',
    tags: ['Risk', 'Capital Preservation'],
    fullContent: 'The 2% rule is a strict risk management guideline. By limiting the risk of any single trade to 2% of the total account balance, a trader can survive a long string of losses without blowing up their account.',
    vector: [0.1, 0.9]
  },
  {
    id: '4',
    title: 'Head and Shoulders',
    type: 'Pattern',
    relevance: 92,
    summary: 'A trend reversal pattern indicating a shift from bullish to bearish.',
    tags: ['Reversal', 'Bearish'],
    fullContent: 'A technical analysis pattern described by three peaks, the outside two being close in height and the middle is highest. It signals a shift from an upward trend to a downward trend.',
    vector: [0.75, 0.6]
  },
  {
    id: '5',
    title: 'Overtrading Burnout',
    type: 'Lesson',
    relevance: 78,
    summary: 'Executing too many trades leads to decision fatigue and errors.',
    tags: ['Discipline', 'Psychology'],
    fullContent: 'Overtrading can result from greed or boredom. It increases transaction costs and often involves taking low-quality setups, leading to underperformance.',
    vector: [-0.5, -0.3]
  }
];

export const KnowledgeHub: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'Pattern' | 'Lesson' | 'Rule'>('Pattern');
  const [searchQuery, setSearchQuery] = useState('');
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [items, setItems] = useState<KnowledgeItem[]>(mockKnowledge);
  const [isLoading, setIsLoading] = useState(false);

  const fetchKnowledge = async (query = '', type = activeTab) => {
    setIsLoading(true);
    try {
      // Simulation delay as requested
      await new Promise(resolve => setTimeout(resolve, 600));
      
      const typeParam = type.toLowerCase() + 's';
      const result = await strategyApi.getKnowledge<any>(typeParam, query);
      const newData = Array.isArray(result?.data)
        ? result.data
        : Array.isArray(result)
          ? result
          : [];
      setItems(newData.length > 0 ? newData : mockKnowledge.filter(item => item.type === type));
    } catch (error) {
      console.warn('Knowledge API failed, falling back to mock:', error);
      // Fallback to mock + filter
      const filtered = mockKnowledge.filter(item => 
        item.type === type && 
        (item.title.toLowerCase().includes(query.toLowerCase()) || 
         item.tags.some(t => t.toLowerCase().includes(query.toLowerCase())))
      );
      setItems(filtered);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchKnowledge('', activeTab);
  }, [activeTab]);

  const handleSearch = () => {
    fetchKnowledge(searchQuery, activeTab);
  };

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header Section */}
      <div className="p-6 border-b border-border bg-bg-card/30">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
          <div>
            <h1 className="text-2xl font-orbitron font-bold text-white tracking-wider flex items-center gap-3">
              <BookOpen className="text-neon-cyan h-6 w-6" />
              知识库 <span className="text-neon-cyan/50 text-xs font-mono ml-2">V2.0_语义搜索</span>
            </h1>
            <p className="text-info-gray/60 text-xs mt-1 uppercase tracking-widest">交易智慧与规则的语义发现系统</p>
          </div>

          {/* Search Bar */}
          <div className="relative group max-w-md w-full">
            <div className="absolute inset-0 bg-neon-cyan/20 blur-md opacity-0 group-focus-within:opacity-100 transition-opacity rounded-md" />
            <div className="relative flex items-center bg-bg-primary border border-border group-focus-within:border-neon-cyan transition-all rounded-md px-4 py-2">
              <Search className="h-4 w-4 text-info-gray group-focus-within:text-neon-cyan" />
              <input 
                type="text" 
                placeholder="搜索交易模式、经验教训或风控规则..."
                className="bg-transparent border-none outline-none text-sm text-white px-3 flex-1 font-inter"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
              />
              <button 
                onClick={handleSearch}
                disabled={isLoading}
                className="text-[10px] font-mono bg-neon-cyan/10 border border-neon-cyan/30 text-neon-cyan px-2 py-1 rounded-sm hover:bg-neon-cyan hover:text-black transition-colors shadow-[0_0_10px_rgba(0,240,255,0.2)] flex items-center gap-1"
              >
                {isLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : '搜索'}
              </button>
            </div>
          </div>
        </div>
      </div>

      <div className="flex-1 flex overflow-hidden">
        {/* Left Side: Search Results & Tabs */}
        <div className="flex-1 flex flex-col border-r border-border overflow-hidden bg-bg-primary/20">
          {/* Tabs */}
          <div className="flex border-b border-border">
            {(['Pattern', 'Lesson', 'Rule'] as const).map(tab => (
              <button
                key={tab}
                onClick={() => { setActiveTab(tab); setExpandedId(null); }}
                className={cn(
                  "flex-1 py-3 text-xs font-orbitron tracking-widest uppercase transition-all border-b-2",
                  activeTab === tab 
                    ? "text-neon-cyan border-neon-cyan bg-neon-cyan/5" 
                    : "text-info-gray/40 border-transparent hover:text-info-gray/80 hover:bg-white/5"
                )}
              >
                {tab === 'Pattern' ? '模式' : tab === 'Lesson' ? '经验' : '规则'}
              </button>
            ))}
          </div>

          {/* Results List */}
          <div className="flex-1 overflow-y-auto custom-scrollbar p-4 space-y-4">
            {isLoading && items.length === 0 ? (
              <div className="h-64 flex items-center justify-center">
                <Loader2 className="h-8 w-8 text-neon-cyan animate-spin opacity-50" />
              </div>
            ) : items.map(item => (
              <div 
                key={item.id}
                className={cn(
                  "group border border-border bg-bg-card/50 rounded-md transition-all overflow-hidden",
                  expandedId === item.id ? "ring-1 ring-neon-cyan/50 shadow-[0_0_20px_rgba(0,240,255,0.1)]" : "hover:border-info-gray/30"
                )}
              >
                <div 
                  className="p-4 cursor-pointer"
                  onClick={() => setExpandedId(expandedId === item.id ? null : item.id)}
                >
                  <div className="flex justify-between items-start mb-2">
                    <h3 className="font-orbitron text-white text-sm tracking-wide">{item.title}</h3>
                    <div className="flex items-center gap-2">
                      <div className="text-[10px] text-info-gray/60 font-mono">语义相关度</div>
                      <div className="w-16 h-1.5 bg-bg-hover rounded-full overflow-hidden">
                        <div 
                          className="h-full bg-neon-cyan shadow-[0_0_5px_rgba(0,240,255,0.8)]" 
                          style={{ width: `${item.relevance}%` }}
                        />
                      </div>
                    </div>
                  </div>
                  <p className="text-xs text-info-gray/80 line-clamp-2 mb-3">{item.summary}</p>
                  <div className="flex flex-wrap gap-2">
                    {item.tags.map(tag => (
                      <span key={tag} className="text-[9px] font-mono bg-bg-hover text-info-gray/60 px-1.5 py-0.5 rounded border border-border">
                        #{tag}
                      </span>
                    ))}
                  </div>
                </div>

                {expandedId === item.id && (
                  <div className="px-4 pb-4 pt-2 border-t border-border bg-bg-primary/40 animate-in slide-in-from-top-2 duration-300">
                    <div className="text-xs text-info-gray leading-relaxed mb-4 p-3 bg-bg-card rounded border border-border/50">
                      {item.fullContent}
                    </div>
                    <div className="flex justify-end gap-3">
                      <button className="flex items-center gap-1.5 text-[10px] font-mono text-neon-cyan hover:text-white transition-colors">
                        <Save className="h-3 w-3" /> 摄入记忆
                      </button>
                      <button className="flex items-center gap-1.5 text-[10px] font-mono text-up-red hover:text-white transition-colors">
                        <Trash2 className="h-3 w-3" /> 删除
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ))}

            {!isLoading && items.length === 0 && (
              <div className="h-64 flex flex-col items-center justify-center text-info-gray/40 italic text-sm">
                当前分类下未找到匹配项。
              </div>
            )}
          </div>
        </div>

        {/* Right Side: Stats & Vector Space */}
        <div className="w-[320px] bg-bg-card/20 flex flex-col border-l border-border overflow-hidden">
          {/* Stats Panel */}
          <div className="p-4 border-b border-border bg-bg-card/40">
            <h4 className="text-[10px] font-orbitron text-neon-cyan tracking-[0.2em] uppercase mb-4 flex items-center gap-2">
              <BarChart2 className="h-3 w-3" /> 核心统计
            </h4>
            <div className="grid grid-cols-2 gap-3">
              {[
                { label: '总条目', value: '1,284', color: 'text-white' },
                { label: '今日新增', value: '+12', color: 'text-up-green' },
                { label: '向量维度', value: '768-D', color: 'text-info-gray' },
                { label: '在线时长', value: '99.9%', color: 'text-neon-cyan' }
              ].map(stat => (
                <div key={stat.label} className="bg-bg-primary/50 border border-border p-3 rounded">
                  <div className="text-[8px] text-info-gray/40 font-mono mb-1">{stat.label}</div>
                  <div className={cn("text-lg font-orbitron", stat.color)}>{stat.value}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Vector Space Projection */}
          <div className="flex-1 p-4 flex flex-col overflow-hidden">
            <h4 className="text-[10px] font-orbitron text-neon-cyan tracking-[0.2em] uppercase mb-4 flex items-center justify-between">
              <span>向量空间投影</span>
              <Info className="h-3 w-3 text-info-gray/40 cursor-help" />
            </h4>
            <div className="flex-1 relative bg-bg-primary/50 border border-border rounded overflow-hidden">
              {/* Grid Lines */}
              <div className="absolute inset-0 opacity-10 pointer-events-none">
                {[...Array(5)].map((_, i) => (
                  <div key={i} className="absolute w-full h-px bg-info-gray" style={{ top: `${(i+1)*20}%` }} />
                ))}
                {[...Array(5)].map((_, i) => (
                  <div key={i} className="absolute h-full w-px bg-info-gray" style={{ left: `${(i+1)*20}%` }} />
                ))}
              </div>

              {/* SVG Scatter Plot */}
              <svg className="absolute inset-0 w-full h-full p-6 overflow-visible">
                {mockKnowledge.map(item => (
                  <circle
                    key={item.id}
                    cx={`${((item.vector[0] + 1) / 2) * 100}%`}
                    cy={`${((item.vector[1] + 1) / 2) * 100}%`}
                    r="4"
                    fill={item.type === 'Pattern' ? '#00f0ff' : item.type === 'Lesson' ? '#ffdf32' : '#ff3232'}
                    className="cursor-pointer hover:r-6 transition-all drop-shadow-[0_0_5px_currentColor]"
                    onMouseEnter={() => {}} // Could show tooltip
                  />
                ))}
              </svg>

              {/* Legend */}
              <div className="absolute bottom-2 left-2 flex gap-3 text-[8px] font-mono text-info-gray/60">
                <div className="flex items-center gap-1"><div className="w-1.5 h-1.5 bg-neon-cyan rounded-full" /> 模式</div>
                <div className="flex items-center gap-1"><div className="w-1.5 h-1.5 bg-warn-gold rounded-full" /> 经验</div>
                <div className="flex items-center gap-1"><div className="w-1.5 h-1.5 bg-up-red rounded-full" /> 规则</div>
              </div>
            </div>
          </div>

          <div className="p-4 bg-bg-card/40 border-t border-border">
            <div className="bg-neon-cyan/5 border border-neon-cyan/20 p-3 rounded">
              <div className="text-[9px] font-orbitron text-neon-cyan mb-1">最活跃条目</div>
              <div className="text-[11px] text-white font-medium mb-1">MACD 交叉背离</div>
              <div className="text-[8px] text-info-gray/60">更新于 14 分钟前，来自行情流分析</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default KnowledgeHub;
