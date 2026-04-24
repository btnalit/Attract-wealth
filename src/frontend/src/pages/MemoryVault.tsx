import { useCallback, useEffect, useMemo, useState, type FC } from 'react';
import { strategyApi } from '../services/api';

type MemoryTier = 'HOT' | 'WARM' | 'COLD';

interface MemoryEntry {
  id: string;
  type: MemoryTier;
  content: string;
  summary: string;
  tags: string[];
  importance: number | null;
  createdAt: string;
  accessCount: number | null;
  lastAccess: string;
}

const toOptionalNumber = (value: unknown): number | null => {
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
};

const toDateText = (value: unknown): string => {
  const raw = toOptionalNumber(value);
  if (raw !== null && raw > 0) {
    const ts = raw > 1_000_000_000_000 ? raw : raw * 1000;
    return new Date(ts).toLocaleString('zh-CN');
  }
  if (typeof value === 'string' && value.trim()) {
    return value;
  }
  return '--';
};

const normalizeMemoryEntry = (raw: unknown, index: number): MemoryEntry => {
  const row = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>;
  const relevanceRaw = toOptionalNumber(row.relevance ?? row.score);
  const relevance = relevanceRaw === null ? null : Math.max(0, Math.min(100, relevanceRaw));
  const rawTier = String(row.memory_tier ?? row.tier ?? '').trim().toUpperCase();
  const baseTier: MemoryTier = rawTier === 'HOT' ? 'HOT' : rawTier === 'COLD' ? 'COLD' : 'WARM';
  const created = toDateText(row.created_at ?? row.createdAt ?? row.updated_at);
  const tags = Array.isArray(row.tags) ? row.tags.map((item) => String(item)).filter(Boolean) : [];
  const accessCountRaw = toOptionalNumber(row.access_count ?? row.accessCount);
  return {
    id: String(row.id ?? `MEM_${index + 1}`),
    type: baseTier,
    content: String(row.fullContent ?? row.content ?? row.summary ?? ''),
    summary: String(row.title ?? row.summary ?? `记忆条目 ${index + 1}`),
    tags,
    importance: relevance === null ? null : Number((relevance / 100).toFixed(4)),
    createdAt: created,
    accessCount: accessCountRaw === null ? null : Math.max(0, Math.round(accessCountRaw)),
    lastAccess: toDateText(row.last_access ?? row.lastAccess ?? row.updated_at),
  };
};

const normalizeMemoryTier = (value: unknown): MemoryTier => {
  const tier = String(value ?? '').trim().toUpperCase();
  if (tier === 'HOT') return 'HOT';
  if (tier === 'COLD') return 'COLD';
  return 'WARM';
};

const normalizeMemoryOverrides = (
  raw: unknown,
): { tiers: Record<string, MemoryTier>; forgotten: Record<string, true> } => {
  const row = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>;
  const rawTiers = (row.tiers && typeof row.tiers === 'object' ? row.tiers : {}) as Record<string, unknown>;
  const rawForgotten = Array.isArray(row.forgotten) ? row.forgotten : [];
  const tiers: Record<string, MemoryTier> = {};
  const forgotten: Record<string, true> = {};
  Object.entries(rawTiers).forEach(([id, tier]) => {
    const key = String(id ?? '').trim();
    if (!key) return;
    tiers[key] = normalizeMemoryTier(tier);
  });
  rawForgotten.forEach((item) => {
    const key = String(item ?? '').trim();
    if (!key) return;
    forgotten[key] = true;
  });
  return { tiers, forgotten };
};

export const MemoryVault: FC = () => {
  const [activeTab, setActiveTab] = useState<MemoryTier>('HOT');
  const [search, setSearch] = useState('');
  const [allMemories, setAllMemories] = useState<MemoryEntry[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [actionKey, setActionKey] = useState('');
  const [overrideTierMap, setOverrideTierMap] = useState<Record<string, MemoryTier>>({});
  const [forgottenSet, setForgottenSet] = useState<Record<string, true>>({});

  const fetchMemories = useCallback(async (query: string) => {
    setIsLoading(true);
    setError('');
    try {
      const [payload, overridesPayload] = await Promise.all([
        strategyApi.getKnowledge<unknown[]>('all', query),
        strategyApi.getMemoryOverrides<unknown>(),
      ]);
      const rows = Array.isArray(payload) ? payload : [];
      const normalized = rows.map((item, index) => normalizeMemoryEntry(item, index));
      const normalizedOverrides = normalizeMemoryOverrides(overridesPayload);
      setAllMemories(normalized);
      setOverrideTierMap(normalizedOverrides.tiers);
      setForgottenSet(normalizedOverrides.forgotten);
      if (normalized.length > 0) {
        setSelectedId((prev) => prev || normalized[0].id);
      }
    } catch (err) {
      setAllMemories([]);
      setOverrideTierMap({});
      setForgottenSet({});
      setError(`记忆数据拉取失败: ${String(err)}`);
      setSelectedId(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchMemories(search);
  }, [fetchMemories, search]);

  const effectiveMemories = useMemo(() => {
    return allMemories
      .filter((item) => !forgottenSet[item.id])
      .map((item) => ({
        ...item,
        type: overrideTierMap[item.id] ?? item.type,
      }));
  }, [allMemories, forgottenSet, overrideTierMap]);

  const filteredMemories = useMemo(() => {
    const text = search.trim().toLowerCase();
    return effectiveMemories.filter(
      (item) =>
        item.type === activeTab &&
        (!text ||
          item.summary.toLowerCase().includes(text) ||
          item.content.toLowerCase().includes(text) ||
          item.tags.some((tag) => tag.toLowerCase().includes(text))),
    );
  }, [activeTab, effectiveMemories, search]);

  const selectedMemory = useMemo(() => {
    if (filteredMemories.length === 0) return null;
    return filteredMemories.find((item) => item.id === selectedId) ?? filteredMemories[0];
  }, [filteredMemories, selectedId]);

  useEffect(() => {
    if (!selectedMemory) {
      setSelectedId(null);
      return;
    }
    if (selectedId !== selectedMemory.id) {
      setSelectedId(selectedMemory.id);
    }
  }, [selectedId, selectedMemory]);

  const handlePromote = async (id: string) => {
    const current = effectiveMemories.find((item) => item.id === id);
    if (!current) return;
    setActionKey(`promote:${id}`);
    setError('');
    setMessage('');
    try {
      const payload = await strategyApi.promoteMemory<{ tier?: string }>({
        id,
        current_tier: current.type,
      });
      const nextTier = normalizeMemoryTier(payload?.tier ?? current.type);
      setOverrideTierMap((prev) => ({ ...prev, [id]: nextTier }));
      setForgottenSet((prev) => {
        if (!prev[id]) return prev;
        const next = { ...prev };
        delete next[id];
        return next;
      });
      setMessage(`条目 ${id} 已提升到 ${nextTier} 层。`);
    } catch (err) {
      setError(`记忆操作失败: ${String(err)}`);
    } finally {
      setActionKey('');
    }
  };

  const handleDemote = async (id: string) => {
    const current = effectiveMemories.find((item) => item.id === id);
    if (!current) return;
    setActionKey(`demote:${id}`);
    setError('');
    setMessage('');
    try {
      const payload = await strategyApi.demoteMemory<{ tier?: string }>({
        id,
        current_tier: current.type,
      });
      const nextTier = normalizeMemoryTier(payload?.tier ?? current.type);
      setOverrideTierMap((prev) => ({ ...prev, [id]: nextTier }));
      setForgottenSet((prev) => {
        if (!prev[id]) return prev;
        const next = { ...prev };
        delete next[id];
        return next;
      });
      setMessage(`条目 ${id} 已降低到 ${nextTier} 层。`);
    } catch (err) {
      setError(`记忆操作失败: ${String(err)}`);
    } finally {
      setActionKey('');
    }
  };

  const handleForget = async (id: string) => {
    setActionKey(`forget:${id}`);
    setError('');
    setMessage('');
    try {
      await strategyApi.forgetMemory<{ forgotten?: boolean }>({ id });
      setForgottenSet((prev) => ({ ...prev, [id]: true }));
      setMessage(`条目 ${id} 已标记为遗忘。`);
    } catch (err) {
      setError(`记忆操作失败: ${String(err)}`);
    } finally {
      setActionKey('');
    }
  };

  return (
    <div className="flex h-[calc(100vh-80px)] w-full bg-[#0a0a0f] text-gray-400 font-mono overflow-hidden">
      <aside className="w-16 border-r border-gray-800 flex flex-col items-center py-6 space-y-8 bg-black/40">
        {(['HOT', 'WARM', 'COLD'] as const).map((tier) => (
          <button
            key={tier}
            onClick={() => setActiveTab(tier)}
            className={`group relative p-3 rounded transition-all ${
              activeTab === tier
                ? tier === 'HOT'
                  ? 'text-neon-cyan shadow-[0_0_15px_rgba(0,255,255,0.2)]'
                  : tier === 'WARM'
                    ? 'text-orange-400 shadow-[0_0_15px_rgba(251,146,60,0.2)]'
                    : 'text-blue-400 shadow-[0_0_15px_rgba(96,165,250,0.2)]'
                : 'hover:text-gray-200'
            }`}
          >
            <div className={`text-[10px] font-bold tracking-tighter ${activeTab === tier ? 'opacity-100' : 'opacity-40'}`}>
              {tier === 'HOT' ? '热记忆' : tier === 'WARM' ? '温记忆' : '冷记忆'}
            </div>
            {activeTab === tier && <div className="absolute -left-1 top-1/2 -translate-y-1/2 w-1 h-6 bg-neon-cyan" />}
          </button>
        ))}
      </aside>

      <div className="w-[450px] border-r border-gray-800 flex flex-col bg-black/20">
        <div className="p-4 border-b border-gray-800 space-y-2">
          <div className="relative">
            <input
              type="text"
              placeholder="搜索记忆金库..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full bg-black/60 border border-gray-800 rounded px-4 py-2 text-xs focus:border-neon-cyan outline-none transition-all placeholder:text-gray-700"
            />
            <div className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] text-gray-700">LIVE</div>
          </div>
          {error && <div className="text-[10px] text-red-400">{error}</div>}
          {message && <div className="text-[10px] text-neon-cyan">{message}</div>}
        </div>
        <div className="flex-1 overflow-auto custom-scrollbar">
          {isLoading ? (
            <div className="p-5 text-xs text-info-gray/60">加载中...</div>
          ) : filteredMemories.length === 0 ? (
            <div className="p-5 text-xs text-info-gray/60">当前层级无匹配记忆。</div>
          ) : (
            filteredMemories.map((m) => (
              <div
                key={m.id}
                onClick={() => setSelectedId(m.id)}
                className={`p-5 border-b border-gray-900 cursor-pointer transition-all ${
                  selectedId === m.id ? 'bg-neon-cyan/5 border-l-2 border-l-neon-cyan' : 'hover:bg-gray-800/20'
                }`}
              >
                <div className="flex justify-between items-start mb-2">
                  <span className="text-[10px] font-orbitron text-neon-cyan/60">{m.id}</span>
                  <span className="text-[9px] text-gray-600">{m.createdAt}</span>
                </div>
                <h4 className="text-xs font-bold text-gray-200 mb-2 truncate uppercase">{m.summary}</h4>
                <div className="flex flex-wrap gap-2">
                  {m.tags.map((tag) => (
                    <span key={tag} className="text-[8px] px-1.5 py-0.5 border border-gray-800 rounded text-gray-500 uppercase">
                      #{tag}
                    </span>
                  ))}
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      <div className="flex-1 flex flex-col relative">
        <div
          className="absolute inset-0 opacity-[0.02] pointer-events-none"
          style={{ backgroundImage: 'radial-gradient(#fff 1px, transparent 0)', backgroundSize: '24px 24px' }}
        />

        <div className="flex-1 p-10 flex flex-col z-10">
          <div className="max-w-3xl w-full mx-auto flex flex-col h-full">
            {!selectedMemory ? (
              <div className="h-full flex items-center justify-center text-sm text-info-gray/50">
                选择左侧记忆条目查看详情
              </div>
            ) : (
              <>
                <div className="flex justify-between items-start mb-10 border-b border-gray-800 pb-6">
                  <div>
                    <div className="flex items-center gap-3 mb-2">
                      <span
                        className={`px-2 py-0.5 rounded-sm text-[10px] font-bold ${
                          selectedMemory.type === 'HOT'
                            ? 'bg-neon-cyan/20 text-neon-cyan'
                            : selectedMemory.type === 'WARM'
                              ? 'bg-orange-500/20 text-orange-500'
                              : 'bg-blue-500/20 text-blue-500'
                        }`}
                      >
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
                    <div className={`text-sm ${selectedMemory.importance === null ? 'text-info-gray/60' : 'text-neon-magenta'}`}>
                      {selectedMemory.importance === null ? '--' : `${(selectedMemory.importance * 100).toFixed(0)}%`}
                    </div>
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
                        <div className={`text-[10px] ${selectedMemory.accessCount === null ? 'text-info-gray/60' : 'text-neon-cyan'}`}>
                          {selectedMemory.accessCount === null ? '--' : selectedMemory.accessCount}
                        </div>
                      </div>
                      <div className="bg-black/40 p-3 rounded border border-gray-800">
                        <div className="text-[9px] text-gray-600 mb-1 uppercase">生存周期状态</div>
                        <div className="text-[10px] text-green-400">
                          {selectedMemory.type === 'HOT' ? 'Active' : selectedMemory.type === 'WARM' ? 'Warm' : 'Archived'}
                        </div>
                      </div>
                    </div>
                  </section>
                </div>

                <div className="mt-8 grid grid-cols-2 gap-3 pt-4 border-t border-gray-800">
                  <button
                    onClick={() => void handlePromote(selectedMemory.id)}
                    disabled={actionKey.length > 0}
                    className="px-4 py-2 bg-neon-cyan/10 border border-neon-cyan/40 text-neon-cyan text-[10px] rounded hover:bg-neon-cyan/20 transition-all font-orbitron"
                  >
                    {actionKey === `promote:${selectedMemory.id}` ? '处理中...' : selectedMemory.type === 'HOT' ? '保持热层' : '提升层级'}
                  </button>
                  <button
                    onClick={() => void handleDemote(selectedMemory.id)}
                    disabled={actionKey.length > 0}
                    className="px-4 py-2 bg-neon-magenta/10 border border-neon-magenta/40 text-neon-magenta text-[10px] rounded hover:bg-neon-magenta/20 transition-all font-orbitron"
                  >
                    {actionKey === `demote:${selectedMemory.id}` ? '处理中...' : selectedMemory.type === 'COLD' ? '保持冷层' : '降低层级'}
                  </button>
                  <button
                    onClick={() => void handleForget(selectedMemory.id)}
                    disabled={actionKey.length > 0}
                    className="col-span-2 px-4 py-2 bg-red-900/20 border border-red-900/40 text-red-500 text-[10px] rounded hover:bg-red-900/40 transition-all font-orbitron mt-2"
                  >
                    {actionKey === `forget:${selectedMemory.id}` ? '处理中...' : '遗忘记忆'}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default MemoryVault;
