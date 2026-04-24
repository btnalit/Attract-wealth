import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Search, BookOpen, Trash2, Save, BarChart2, Info, Loader2 } from 'lucide-react';
import { cn } from '../lib/utils';
import { strategyApi } from '../services/api';

type KnowledgeTab = 'Pattern' | 'Lesson' | 'Rule';

interface KnowledgeItem {
  id: string;
  title: string;
  type: KnowledgeTab;
  relevance: number | null;
  summary: string;
  tags: string[];
  fullContent: string;
  vector: [number, number] | null;
}

const TAB_TO_QUERY: Record<KnowledgeTab, string> = {
  Pattern: 'pattern',
  Lesson: 'lesson',
  Rule: 'rule',
};

const normalizeType = (value: unknown): KnowledgeTab => {
  const text = String(value ?? '').trim().toLowerCase();
  if (text === 'pattern') return 'Pattern';
  if (text === 'lesson') return 'Lesson';
  return 'Rule';
};

const normalizeVector = (value: unknown): [number, number] | null => {
  if (Array.isArray(value) && value.length >= 2) {
    const x = Number(value[0]);
    const y = Number(value[1]);
    if (Number.isFinite(x) && Number.isFinite(y)) {
      const nx = Math.max(-1, Math.min(1, x));
      const ny = Math.max(-1, Math.min(1, y));
      return [nx, ny];
    }
  }
  return null;
};

const toOptionalNumber = (value: unknown): number | null => {
  if (value === null || value === undefined) {
    return null;
  }
  if (typeof value === 'string' && value.trim() === '') {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

const normalizeKnowledgeItem = (raw: unknown, index: number): KnowledgeItem => {
  const row = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>;
  const id = String(row.id ?? `kb_${index}`);
  const title = String(row.title ?? row.name ?? `Knowledge ${index + 1}`);
  const type = normalizeType(row.type);
  const relevanceRaw = toOptionalNumber(row.relevance ?? row.score);
  const relevance = relevanceRaw === null ? null : Math.max(0, Math.min(100, relevanceRaw));
  const summary = String(row.summary ?? row.description ?? '');
  const fullContent = String(row.fullContent ?? row.content ?? summary);
  const tags = Array.isArray(row.tags) ? row.tags.map((item) => String(item)).filter(Boolean) : [];
  const vector = normalizeVector(row.vector);
  return {
    id,
    title,
    type,
    relevance,
    summary,
    tags,
    fullContent,
    vector,
  };
};

export const KnowledgeHub: React.FC = () => {
  const [activeTab, setActiveTab] = useState<KnowledgeTab>('Pattern');
  const [searchQuery, setSearchQuery] = useState('');
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [items, setItems] = useState<KnowledgeItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [actionMessage, setActionMessage] = useState('');
  const [actionKey, setActionKey] = useState('');
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);

  const fetchKnowledge = useCallback(async (query: string, tab: KnowledgeTab) => {
    setIsLoading(true);
    setError('');
    setActionMessage('');
    try {
      const payload = await strategyApi.getKnowledge<unknown[]>(TAB_TO_QUERY[tab], query);
      const rows = Array.isArray(payload) ? payload : [];
      const normalized = rows.map((item, index) => normalizeKnowledgeItem(item, index));
      setItems(normalized);
      setUpdatedAt(Date.now());
    } catch (err) {
      setItems([]);
      setError(`知识检索失败: ${String(err)}`);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchKnowledge('', activeTab);
  }, [activeTab, fetchKnowledge]);

  const stats = useMemo(() => {
    const total = items.length;
    const relevanceSamples = items
      .map((item) => item.relevance)
      .filter((value): value is number => value !== null && Number.isFinite(value));
    const avgRelevance =
      relevanceSamples.length > 0
        ? relevanceSamples.reduce((sum, value) => sum + value, 0) / relevanceSamples.length
        : null;
    const highRelevance = relevanceSamples.length > 0 ? relevanceSamples.filter((value) => value >= 80).length : null;
    const tagSet = new Set<string>();
    items.forEach((item) => item.tags.forEach((tag) => tagSet.add(tag)));
    return {
      total,
      avgRelevance: avgRelevance === null ? null : Number(avgRelevance.toFixed(2)),
      highRelevance,
      uniqueTags: tagSet.size,
    };
  }, [items]);

  const topEntry = useMemo(() => {
    const ranked = items.filter((item) => item.relevance !== null);
    if (ranked.length === 0) return null;
    return [...ranked].sort((a, b) => (b.relevance ?? -Infinity) - (a.relevance ?? -Infinity))[0];
  }, [items]);

  const handleSearch = () => {
    void fetchKnowledge(searchQuery, activeTab);
  };

  const handleActionClick = async (action: 'ingest' | 'delete', item: KnowledgeItem) => {
    const key = `${action}:${item.id}`;
    setActionKey(key);
    setError('');
    setActionMessage('');
    try {
      if (action === 'ingest') {
        const payload = await strategyApi.ingestKnowledge<{ id?: string }>({
          type: item.type === 'Pattern' ? 'pattern' : item.type === 'Lesson' ? 'lesson' : 'rule',
          title: item.title,
          content: item.fullContent || item.summary,
          tags: item.tags,
          priority: item.type === 'Rule' ? 1 : 0,
          context: item.type === 'Pattern' ? { source: 'knowledge_hub_ui', original_id: item.id } : undefined,
        });
        const nextId = String(payload?.id ?? '').trim();
        setActionMessage(nextId ? `条目 ${item.id} 已摄入（新ID: ${nextId}）。` : `条目 ${item.id} 已摄入。`);
        await fetchKnowledge(searchQuery, activeTab);
        return;
      }

      await strategyApi.deleteKnowledge<{ id?: string; deleted?: boolean }>({ id: item.id });
      setItems((prev) => prev.filter((row) => row.id !== item.id));
      if (expandedId === item.id) {
        setExpandedId(null);
      }
      setActionMessage(`条目 ${item.id} 已删除。`);
    } catch (err) {
      setError(`知识操作失败: ${String(err)}`);
    } finally {
      setActionKey('');
    }
  };

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="p-6 border-b border-border bg-bg-card/30">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
          <div>
            <h1 className="text-2xl font-orbitron font-bold text-white tracking-wider flex items-center gap-3">
              <BookOpen className="text-neon-cyan h-6 w-6" />
              知识库 <span className="text-neon-cyan/50 text-xs font-mono ml-2">LIVE_SEARCH</span>
            </h1>
            <p className="text-info-gray/60 text-xs mt-1 uppercase tracking-widest">
              交易智慧与规则的语义发现系统
            </p>
          </div>

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
        {error && <div className="mt-3 text-xs text-down-red">{error}</div>}
        {actionMessage && <div className="mt-2 text-xs text-warn-gold">{actionMessage}</div>}
      </div>

      <div className="flex-1 flex overflow-hidden">
        <div className="flex-1 flex flex-col border-r border-border overflow-hidden bg-bg-primary/20">
          <div className="flex border-b border-border">
            {(['Pattern', 'Lesson', 'Rule'] as const).map((tab) => (
              <button
                key={tab}
                onClick={() => {
                  setActiveTab(tab);
                  setExpandedId(null);
                }}
                className={cn(
                  'flex-1 py-3 text-xs font-orbitron tracking-widest uppercase transition-all border-b-2',
                  activeTab === tab
                    ? 'text-neon-cyan border-neon-cyan bg-neon-cyan/5'
                    : 'text-info-gray/40 border-transparent hover:text-info-gray/80 hover:bg-white/5',
                )}
              >
                {tab === 'Pattern' ? '模式' : tab === 'Lesson' ? '经验' : '规则'}
              </button>
            ))}
          </div>

          <div className="flex-1 overflow-y-auto custom-scrollbar p-4 space-y-4">
            {isLoading && items.length === 0 ? (
              <div className="h-64 flex items-center justify-center">
                <Loader2 className="h-8 w-8 text-neon-cyan animate-spin opacity-50" />
              </div>
            ) : (
              items.map((item) => (
                <div
                  key={item.id}
                  className={cn(
                    'group border border-border bg-bg-card/50 rounded-md transition-all overflow-hidden',
                    expandedId === item.id
                      ? 'ring-1 ring-neon-cyan/50 shadow-[0_0_20px_rgba(0,240,255,0.1)]'
                      : 'hover:border-info-gray/30',
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
                            className={cn(
                              'h-full',
                              item.relevance === null
                                ? 'bg-info-gray/40'
                                : 'bg-neon-cyan shadow-[0_0_5px_rgba(0,240,255,0.8)]',
                            )}
                            style={{ width: `${item.relevance === null ? 0 : Math.max(0, Math.min(100, item.relevance))}%` }}
                          />
                        </div>
                        <div className={cn('text-[10px] font-mono', item.relevance === null ? 'text-info-gray/60' : 'text-neon-cyan')}>
                          {item.relevance === null ? '--' : item.relevance.toFixed(1)}
                        </div>
                      </div>
                    </div>
                    <p className="text-xs text-info-gray/80 line-clamp-2 mb-3">{item.summary}</p>
                    <div className="flex flex-wrap gap-2">
                      {item.tags.map((tag) => (
                        <span
                          key={tag}
                          className="text-[9px] font-mono bg-bg-hover text-info-gray/60 px-1.5 py-0.5 rounded border border-border"
                        >
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
                        <button
                          onClick={() => void handleActionClick('ingest', item)}
                          disabled={actionKey.length > 0}
                          className="flex items-center gap-1.5 text-[10px] font-mono text-neon-cyan hover:text-white transition-colors"
                        >
                          {actionKey === `ingest:${item.id}` ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />} 摄入记忆
                        </button>
                        <button
                          onClick={() => void handleActionClick('delete', item)}
                          disabled={actionKey.length > 0}
                          className="flex items-center gap-1.5 text-[10px] font-mono text-up-red hover:text-white transition-colors"
                        >
                          {actionKey === `delete:${item.id}` ? <Loader2 className="h-3 w-3 animate-spin" /> : <Trash2 className="h-3 w-3" />} 删除
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              ))
            )}

            {!isLoading && items.length === 0 && (
              <div className="h-64 flex flex-col items-center justify-center text-info-gray/40 italic text-sm">
                当前分类下未找到匹配项。
              </div>
            )}
          </div>
        </div>

        <div className="w-[320px] bg-bg-card/20 flex flex-col border-l border-border overflow-hidden">
          <div className="p-4 border-b border-border bg-bg-card/40">
            <h4 className="text-[10px] font-orbitron text-neon-cyan tracking-[0.2em] uppercase mb-4 flex items-center gap-2">
              <BarChart2 className="h-3 w-3" /> 核心统计
            </h4>
            <div className="grid grid-cols-2 gap-3">
              {[
                { label: '总条目', value: `${stats.total}`, color: 'text-white' },
                { label: '高相关(>=80)', value: stats.highRelevance === null ? '--' : `${stats.highRelevance}`, color: stats.highRelevance === null ? 'text-info-gray/60' : 'text-up-green' },
                { label: '平均相关度', value: stats.avgRelevance === null ? '--' : `${stats.avgRelevance.toFixed(1)}`, color: stats.avgRelevance === null ? 'text-info-gray/60' : 'text-neon-cyan' },
                { label: '标签数', value: `${stats.uniqueTags}`, color: 'text-info-gray' },
              ].map((stat) => (
                <div key={stat.label} className="bg-bg-primary/50 border border-border p-3 rounded">
                  <div className="text-[8px] text-info-gray/40 font-mono mb-1">{stat.label}</div>
                  <div className={cn('text-lg font-orbitron', stat.color)}>{stat.value}</div>
                </div>
              ))}
            </div>
            <div className="mt-3 text-[10px] text-info-gray/60">
              最近更新时间：{updatedAt !== null && updatedAt > 0 ? new Date(updatedAt).toLocaleString('zh-CN') : '--'}
            </div>
          </div>

          <div className="flex-1 p-4 flex flex-col overflow-hidden">
            <h4 className="text-[10px] font-orbitron text-neon-cyan tracking-[0.2em] uppercase mb-4 flex items-center justify-between">
              <span>向量空间投影</span>
              <Info className="h-3 w-3 text-info-gray/40 cursor-help" />
            </h4>
            <div className="flex-1 relative bg-bg-primary/50 border border-border rounded overflow-hidden">
              <div className="absolute inset-0 opacity-10 pointer-events-none">
                {[...Array(5)].map((_, i) => (
                  <div key={`h-${i}`} className="absolute w-full h-px bg-info-gray" style={{ top: `${(i + 1) * 20}%` }} />
                ))}
                {[...Array(5)].map((_, i) => (
                  <div key={`v-${i}`} className="absolute h-full w-px bg-info-gray" style={{ left: `${(i + 1) * 20}%` }} />
                ))}
              </div>

              <svg className="absolute inset-0 w-full h-full p-6 overflow-visible">
                {items.map((item) => (
                  item.vector ? (
                    <circle
                      key={item.id}
                      cx={`${((item.vector[0] + 1) / 2) * 100}%`}
                      cy={`${((item.vector[1] + 1) / 2) * 100}%`}
                      r="4"
                      fill={item.type === 'Pattern' ? '#00f0ff' : item.type === 'Lesson' ? '#ffdf32' : '#ff3232'}
                      className="cursor-pointer hover:r-6 transition-all drop-shadow-[0_0_5px_currentColor]"
                    />
                  ) : null
                ))}
              </svg>
              {!items.some((item) => item.vector) && (
                <div className="absolute inset-0 flex items-center justify-center text-[10px] text-info-gray/60">
                  暂无可投影的真实向量
                </div>
              )}

              <div className="absolute bottom-2 left-2 flex gap-3 text-[8px] font-mono text-info-gray/60">
                <div className="flex items-center gap-1">
                  <div className="w-1.5 h-1.5 bg-neon-cyan rounded-full" /> 模式
                </div>
                <div className="flex items-center gap-1">
                  <div className="w-1.5 h-1.5 bg-warn-gold rounded-full" /> 经验
                </div>
                <div className="flex items-center gap-1">
                  <div className="w-1.5 h-1.5 bg-up-red rounded-full" /> 规则
                </div>
              </div>
            </div>
          </div>

          <div className="p-4 bg-bg-card/40 border-t border-border">
            <div className="bg-neon-cyan/5 border border-neon-cyan/20 p-3 rounded">
              <div className="text-[9px] font-orbitron text-neon-cyan mb-1">最活跃条目</div>
              <div className="text-[11px] text-white font-medium mb-1">
                {topEntry ? topEntry.title : '暂无条目'}
              </div>
              <div className="text-[8px] text-info-gray/60">
                {topEntry ? `相关度 ${topEntry.relevance?.toFixed(1)} / #${topEntry.tags.join(' #')}` : '等待知识索引返回'}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default KnowledgeHub;
