import { useCallback, useEffect, useMemo, useState, type MouseEvent } from 'react';
import {
  ReactFlow,
  Controls,
  Background,
  Panel,
  Node,
  Edge,
  MarkerType,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useAgentStore, type AgentStatus } from '../store/agentStore';
import { useSSE } from '../hooks/useSSE';
import AgentNode from '../components/AgentNode';
import { monitorApi, tradingApi, type AnalyzeResult, type GraphTopologyPayload } from '../services/api';
import {
  Activity,
  Loader2,
  Monitor,
  Play,
  RotateCcw,
  Search,
} from 'lucide-react';
import { clsx } from 'clsx';

const nodeTypes = {
  agent: AgentNode as any,
} as const;

// 节点中文标签映射（与后端 trading_graph.py 节点名对齐）
const NODE_LABELS: Record<string, string> = {
  fundamental: '基本面分析员',
  technical: '技术面分析员',
  news: '新闻分析员',
  signal_processing: '信号汇聚',
  debate: '辩论研究员',
  trader: '交易决策者',
  risk: '风控守卫',
  reflection: '反思',
  START: '开始',
  END: '输出',
};

// 节点垂直分层布局（按 pipeline 顺序）
function layoutNodes(nodes: string[]): Node[] {
  const filtered = nodes.filter((n) => n !== 'START' && n !== 'END');
  const result: Node[] = [];

  if (nodes.includes('START')) {
    result.push({ id: 'START', type: 'agent', data: { label: '开始', id: 'START' }, position: { x: 300, y: 0 } });
  }
  filtered.forEach((id, i) => {
    result.push({
      id,
      type: 'agent',
      data: { label: NODE_LABELS[id] || id, id },
      position: { x: 250 + (i % 2 === 0 ? -60 : 60), y: 130 * (i + 1) },
    });
  });
  if (nodes.includes('END')) {
    result.push({
      id: 'END',
      type: 'agent',
      data: { label: '输出', id: 'END' },
      position: { x: 300, y: 130 * (filtered.length + 1) },
    });
  }
  return result;
}

function buildEdges(edges: Array<{ from: string; to: string }>): Edge[] {
  return edges.map((e, i) => ({
    id: `e-${i}-${e.from}-${e.to}`,
    source: e.from,
    target: e.to,
    animated: true,
    style: { stroke: '#00f0ff', strokeWidth: 1.5, opacity: 0.6 },
    markerEnd: { type: MarkerType.ArrowClosed, color: '#00f0ff' },
  }));
}

const toOptionalNumber = (value: unknown): number | null => {
  if (value === null || value === undefined) return null;
  if (typeof value === 'string' && value.trim() === '') return null;
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
};

const toTimestamp = (value: unknown): number | null => {
  const num = toOptionalNumber(value);
  if (num === null || num <= 0) return null;
  return num > 1_000_000_000_000 ? num : num * 1000;
};

const resolveWorkshopNodeId = (type: unknown, message: unknown, payload: unknown): string | null => {
  const source = `${String(type ?? '')} ${String(message ?? '')}`.toLowerCase();
  const payloadText = payload && typeof payload === 'object' ? JSON.stringify(payload).toLowerCase() : '';
  const text = `${source} ${payloadText}`;

  if (text.includes('fundamental') || text.includes('基本面')) return 'fundamental';
  if (text.includes('technical') || text.includes('技术')) return 'technical';
  if (text.includes('news') || text.includes('新闻')) return 'news';
  if (text.includes('debate') || text.includes('research') || text.includes('辩论')) return 'debate';
  if (text.includes('risk') || text.includes('风控')) return 'risk';
  if (text.includes('trade') || text.includes('order') || text.includes('下单')) return 'trader';
  if (text.includes('signal')) return 'signal_processing';
  if (text.includes('reflect') || text.includes('反思')) return 'reflection';
  return null;
};

const resolveWorkshopNodeStatus = (severity: unknown, message: unknown): AgentStatus => {
  const sev = String(severity ?? '').trim().toLowerCase();
  const msg = String(message ?? '').trim().toLowerCase();
  if (sev === 'high' || msg.includes('error') || msg.includes('failed') || msg.includes('失败')) return 'error';
  if (msg.includes('pending') || msg.includes('running') || msg.includes('processing') || msg.includes('执行中')) return 'thinking';
  return 'success';
};

const AgentWorkshop = () => {
  const { isConnected } = useSSE();
  const {
    logs,
    activeNodeId,
    resetGraph,
    pnl,
    agents,
    updatePnl,
    clearLogs,
    addLog,
    setActiveNode,
    updateAgentStatus,
  } = useAgentStore();
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [hasPnlSnapshot, setHasPnlSnapshot] = useState(false);

  // 动态拓扑
  const [topologyNodes, setTopologyNodes] = useState<string[]>([]);
  const [topologyEdges, setTopologyEdges] = useState<Array<{ from: string; to: string }>>([]);

  // analyze 触发
  const [tickerInput, setTickerInput] = useState('000001');
  const [analyzeResult, setAnalyzeResult] = useState<AnalyzeResult | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeError, setAnalyzeError] = useState('');

  const onNodeClick = useCallback((_event: MouseEvent, node: Node) => {
    setSelectedNodeId(node.id);
  }, []);

  const selectedNodeLogs = useMemo(() =>
    logs.filter((log) => log.nodeId === (selectedNodeId || activeNodeId)),
    [logs, selectedNodeId, activeNodeId],
  );

  const activeAgentCount = useMemo(
    () => Object.values(agents).filter((item) => item.status === 'thinking').length,
    [agents],
  );

  // 当前选中节点的分析报告
  const selectedReport = useMemo(() => {
    if (!analyzeResult?.state?.analysis_reports || !selectedNodeId) return null;
    return analyzeResult.state.analysis_reports[selectedNodeId] || null;
  }, [analyzeResult, selectedNodeId]);

  const latestUpdateText = useMemo(() => {
    const timestamps = Object.values(agents)
      .map((item) => toOptionalNumber(item.lastUpdate))
      .filter((item): item is number => item !== null && Number.isFinite(item) && item > 0);
    if (timestamps.length === 0) return '--';
    return new Date(Math.max(...timestamps)).toLocaleTimeString();
  }, [agents]);

  const fetchTopology = useCallback(async () => {
    try {
      const payload = await monitorApi.getGraphTopology<GraphTopologyPayload>();
      const nodes = Array.isArray(payload?.nodes) ? payload.nodes : [];
      const edges = Array.isArray(payload?.edges) ? payload.edges : [];
      if (nodes.length > 0) {
        setTopologyNodes(nodes);
        setTopologyEdges(edges);
      }
    } catch (err) {
      console.warn('[AgentWorkshop] topology fetch failed', err);
    }
  }, []);

  const hydrateFromAuditLogs = useCallback(async () => {
    const payload = await monitorApi.getAuditLogs<Array<Record<string, unknown>>>(80);
    const rows = Array.isArray(payload) ? payload : [];
    if (rows.length === 0) return;

    clearLogs();
    let latestNode: string | null = null;
    rows
      .slice()
      .sort((a, b) => {
        const left = toTimestamp(a.timestamp);
        const right = toTimestamp(b.timestamp);
        if (left === null && right === null) return 0;
        if (left === null) return 1;
        if (right === null) return -1;
        return left - right;
      })
      .slice(-80)
      .forEach((item, index) => {
        const message = String(item.message ?? item.detail ?? `${String(item.type ?? 'SYSTEM')} 事件`);
        const nodeId = resolveWorkshopNodeId(item.type, message, item.payload);
        const timestamp = toTimestamp(item.timestamp);
        if (nodeId) {
          latestNode = nodeId;
          const status = resolveWorkshopNodeStatus(item.severity, message);
          const progress = status === 'success' ? 100 : status === 'thinking' ? 60 : 0;
          updateAgentStatus(nodeId, status, undefined, progress);
        }
        addLog({
          timestamp: timestamp === null ? '--' : new Date(timestamp).toLocaleTimeString(),
          nodeId: nodeId || `SYSTEM_${index}`,
          type: 'info',
          message,
        });
      });
    if (latestNode) {
      setActiveNode(latestNode);
    }
  }, [addLog, clearLogs, setActiveNode, updateAgentStatus]);

  const bootstrapWorkshop = useCallback(async () => {
    try {
      const overviewPayload = await monitorApi.getOverview();
      const wallet = overviewPayload?.wallet;
      const pnlValue = toOptionalNumber(wallet?.daily_pnl ?? wallet?.total_pnl);
      if (pnlValue !== null) {
        updatePnl(pnlValue);
        setHasPnlSnapshot(true);
      }
      if (!isConnected || logs.length === 0) {
        await hydrateFromAuditLogs();
      }
    } catch (error) {
      console.warn('[AgentWorkshop] API 启动水位拉取失败', error);
    }
  }, [hydrateFromAuditLogs, isConnected, logs.length, updatePnl]);

  const handleAnalyze = async () => {
    if (!tickerInput.trim()) return;
    setAnalyzing(true);
    setAnalyzeError('');
    try {
      const result = await tradingApi.analyze<AnalyzeResult>(tickerInput.trim());
      setAnalyzeResult(result);
    } catch (err) {
      setAnalyzeError(err instanceof Error ? err.message : String(err));
    } finally {
      setAnalyzing(false);
    }
  };

  useEffect(() => {
    void fetchTopology();
    void bootstrapWorkshop();
  }, [fetchTopology, bootstrapWorkshop]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void bootstrapWorkshop();
    }, 12000);
    return () => window.clearInterval(timer);
  }, [bootstrapWorkshop]);

  const flowNodes = useMemo(() => {
    if (topologyNodes.length > 0) return layoutNodes(topologyNodes);
    return layoutNodes(['fundamental', 'technical', 'news', 'signal_processing', 'debate', 'trader', 'risk', 'reflection']);
  }, [topologyNodes]);

  const flowEdges = useMemo(() => {
    if (topologyEdges.length > 0) return buildEdges(topologyEdges);
    const defaults: Array<{ from: string; to: string }> = [
      { from: 'START', to: 'fundamental' },
      { from: 'fundamental', to: 'technical' },
      { from: 'technical', to: 'news' },
      { from: 'news', to: 'signal_processing' },
      { from: 'signal_processing', to: 'debate' },
      { from: 'debate', to: 'trader' },
      { from: 'trader', to: 'risk' },
      { from: 'risk', to: 'reflection' },
      { from: 'reflection', to: 'END' },
    ];
    return buildEdges(defaults);
  }, [topologyEdges]);

  return (
    <div className="flex h-[calc(100vh-80px)] w-full overflow-hidden bg-bg-primary">
      <div className="relative flex-1 h-full border-r border-border/50 shadow-[inset_0_0_50px_rgba(0,0,0,0.5)]">
        <div className="absolute top-4 left-6 z-10 flex items-center gap-2 px-3 py-1.5 rounded-full bg-bg-card/80 border border-border backdrop-blur-md">
          <Activity className="w-4 h-4 text-neon-cyan" />
          <span className="text-xs font-mono font-bold tracking-[0.2em] text-neon-cyan">LANGGRAPH 引擎</span>
          <span className="mx-2 w-px h-3 bg-border" />
          <div className="flex items-center gap-1.5">
            <div className={clsx('w-1.5 h-1.5 rounded-full shadow-[0_0_8px]', isConnected ? 'bg-up-green' : 'bg-down-red')} />
            <span className="text-[10px] text-info-gray uppercase tracking-wider">{isConnected ? '实时流已激活' : '离线'}</span>
          </div>
        </div>

        <div className="absolute top-16 left-6 z-10 flex items-center gap-2">
          <div className="flex h-8 items-center rounded-sm border border-border bg-bg-card/80 px-2 backdrop-blur-md">
            <Search className="h-3 w-3 text-info-gray/60" />
            <input
              type="text"
              value={tickerInput}
              onChange={(e) => setTickerInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleAnalyze()}
              placeholder="股票代码"
              className="ml-1.5 w-28 bg-transparent text-[10px] font-mono text-white outline-none placeholder:text-info-gray/40"
            />
          </div>
          <button
            onClick={() => void handleAnalyze()}
            disabled={analyzing}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-neon-cyan/20 hover:bg-neon-cyan/30 text-neon-cyan rounded-md border border-neon-cyan/30 transition-all disabled:opacity-50"
          >
            {analyzing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
            <span className="text-[10px] font-bold uppercase tracking-widest font-mono">{analyzing ? '分析中' : '开始分析'}</span>
          </button>
        </div>

        <ReactFlow
          nodes={flowNodes}
          edges={flowEdges}
          nodeTypes={nodeTypes}
          onNodeClick={onNodeClick}
          fitView
          className="react-flow-cyberpunk"
        >
          <Background color="#1e293b" gap={20} size={1} />
          <Controls className="bg-bg-card border-border !fill-info-gray" />

          <Panel position="top-right" className="bg-bg-card/90 border border-border p-2 rounded-lg backdrop-blur-md flex flex-col gap-2">
            <button
              onClick={() => setSelectedNodeId(activeNodeId || '')}
              disabled={!activeNodeId}
              className="flex items-center gap-2 px-4 py-2 bg-neon-cyan/20 hover:bg-neon-cyan/30 text-neon-cyan rounded-md border border-neon-cyan/30 transition-all group disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Play className="w-4 h-4 fill-neon-cyan group-hover:scale-110 transition-transform" />
              <span className="text-xs font-bold uppercase tracking-widest font-mono">聚焦活跃节点</span>
            </button>
            <button
              onClick={() => resetGraph()}
              className="flex items-center gap-2 px-4 py-2 bg-bg-hover hover:bg-bg-card text-info-gray rounded-md border border-border transition-all"
            >
              <RotateCcw className="w-4 h-4" />
              <span className="text-xs font-bold uppercase tracking-widest font-mono">重置图表</span>
            </button>
          </Panel>

          <Panel position="bottom-left" className="bg-bg-card/90 border border-border p-4 rounded-lg backdrop-blur-md">
            <div className="flex flex-col gap-1">
              <span className="text-[10px] text-info-gray uppercase font-mono">本次执行盈亏</span>
              <div className={clsx(
                'text-2xl font-bold font-mono tracking-tighter font-orbitron',
                !hasPnlSnapshot
                  ? 'text-info-gray/70'
                  : pnl >= 0
                    ? 'text-up-green shadow-[0_0_20px_rgba(0,255,157,0.1)]'
                    : 'text-down-red',
              )}>
                {hasPnlSnapshot ? `${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}` : '--'}
              </div>
            </div>
          </Panel>
        </ReactFlow>
      </div>

      <aside className="w-[400px] flex flex-col bg-bg-card border-l border-border">
        <header className="p-4 border-b border-border flex items-center justify-between bg-bg-primary/50">
          <div className="flex items-center gap-2 text-neon-cyan">
            <Monitor className="w-4 h-4" />
            <h2 className="text-xs font-bold uppercase tracking-[0.2em] font-mono">检视器</h2>
          </div>
          <div className="px-2 py-0.5 rounded text-[10px] bg-bg-primary text-info-gray font-mono">
            {selectedNodeId || activeNodeId || '未选择'}
          </div>
        </header>

        <div className="flex-1 overflow-y-auto p-4 space-y-4 custom-scrollbar">
          {analyzeError && (
            <div className="text-[10px] text-down-red p-2 rounded bg-down-red/5 border border-down-red/20">{analyzeError}</div>
          )}

          {selectedReport ? (
            <div className="space-y-3">
              <h3 className="text-[10px] font-bold text-info-gray uppercase tracking-widest flex items-center gap-2">
                <div className="w-1.5 h-1.5 rounded-full bg-neon-cyan" />
                {NODE_LABELS[selectedNodeId || ''] || selectedNodeId} 分析报告
              </h3>
              <div className="grid grid-cols-2 gap-2">
                <div className="p-2 rounded bg-bg-primary/50 border border-border">
                  <span className="text-[9px] text-info-gray/50 uppercase">评分</span>
                  <div className={clsx('text-lg font-bold font-mono', (selectedReport.score ?? 50) > 55 ? 'text-up-green' : (selectedReport.score ?? 50) < 45 ? 'text-down-red' : 'text-info-gray')}>
                    {(selectedReport.score ?? 50).toFixed(1)}
                  </div>
                </div>
                <div className="p-2 rounded bg-bg-primary/50 border border-border">
                  <span className="text-[9px] text-info-gray/50 uppercase">立场</span>
                  <div className={clsx('text-lg font-bold font-mono', String(selectedReport.stance || '').toLowerCase() === 'bullish' ? 'text-up-green' : String(selectedReport.stance || '').toLowerCase() === 'bearish' ? 'text-down-red' : 'text-info-gray')}>
                    {selectedReport.stance || 'Neutral'}
                  </div>
                </div>
              </div>
              {selectedReport.summary && (
                <div className="p-2 rounded bg-bg-primary/40 border border-border/40 text-[10px] text-info-gray/80 leading-relaxed">
                  {selectedReport.summary}
                </div>
              )}
              {selectedReport.key_factors && selectedReport.key_factors.length > 0 && (
                <div className="space-y-1">
                  <span className="text-[9px] text-info-gray/50 uppercase font-bold">关键因素</span>
                  {selectedReport.key_factors.map((f, i) => (
                    <div key={i} className="text-[10px] text-info-gray/70 px-2 py-1 rounded bg-bg-primary/30">• {f}</div>
                  ))}
                </div>
              )}
              {selectedReport.signals && selectedReport.signals.length > 0 && (
                <div className="space-y-1">
                  <span className="text-[9px] text-info-gray/50 uppercase font-bold">规则信号 ({selectedReport.signals.length})</span>
                  {selectedReport.signals.map((sig, i) => (
                    <div key={i} className="p-1.5 rounded bg-bg-primary/40 border border-border/40 text-[10px]">
                      <div className="flex items-center gap-2">
                        <span className={clsx('px-1 rounded font-bold text-[9px]', String(sig.direction).toUpperCase() === 'BULL' ? 'text-up-green' : String(sig.direction).toUpperCase() === 'BEAR' ? 'text-down-red' : 'text-info-gray')}>
                          {sig.direction}
                        </span>
                        <span className="font-mono text-neon-cyan/80 text-[9px]">{sig.rule}</span>
                        <span className="text-info-gray/40 text-[9px]">{sig.strength}</span>
                      </div>
                      <div className="text-info-gray/60 mt-0.5">{sig.description}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : null}

          <div className="space-y-3">
            <h3 className="text-[10px] font-bold text-info-gray uppercase tracking-widest flex items-center gap-2">
              <div className="w-1.5 h-1.5 rounded-full bg-neon-cyan" />
              实时执行链踪
            </h3>
            {selectedNodeLogs.length > 0 ? (
              <div className="space-y-2 font-mono">
                {selectedNodeLogs.map((log, idx) => (
                  <div key={idx} className="group p-2 rounded bg-bg-primary/50 border border-border/50 hover:border-neon-cyan/30 transition-colors">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[9px] text-neon-cyan/70">{log.timestamp}</span>
                    </div>
                    <p className="text-[11px] text-info-gray leading-relaxed">{log.message}</p>
                  </div>
                ))}
              </div>
            ) : (
              <div className="h-24 flex flex-col items-center justify-center border-2 border-dashed border-border rounded-xl">
                <span className="text-[10px] text-info-gray font-mono uppercase">等待日志...</span>
              </div>
            )}
          </div>
        </div>

        <div className="p-4 border-t border-border bg-bg-primary/50 h-[140px]">
          <h3 className="text-[10px] font-bold text-info-gray uppercase tracking-widest mb-3">运行时监控</h3>
          <div className="grid grid-cols-2 gap-3">
            <div className="p-2 bg-bg-card border border-border rounded">
              <span className="text-[9px] text-info-gray uppercase font-mono block mb-1">SSE 连接</span>
              <span className={clsx('text-sm font-bold font-mono', isConnected ? 'text-up-green' : 'text-down-red')}>
                {isConnected ? 'ONLINE' : 'OFFLINE'}
              </span>
            </div>
            <div className="p-2 bg-bg-card border border-border rounded">
              <span className="text-[9px] text-info-gray uppercase font-mono block mb-1">活跃节点</span>
              <span className="text-sm font-bold text-white font-mono">{activeAgentCount}/{flowNodes.length}</span>
            </div>
            <div className="p-2 bg-bg-card border border-border rounded">
              <span className="text-[9px] text-info-gray uppercase font-mono block mb-1">日志缓存</span>
              <span className="text-sm font-bold text-up-green font-mono">{logs.length}</span>
            </div>
            <div className="p-2 bg-bg-card border border-border rounded">
              <span className="text-[9px] text-info-gray uppercase font-mono block mb-1">最近更新</span>
              <span className="text-sm font-bold text-warn-gold font-mono">{latestUpdateText}</span>
            </div>
          </div>
        </div>
      </aside>
    </div>
  );
};

export default AgentWorkshop;
