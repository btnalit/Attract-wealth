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
import { monitorApi, type MonitorOverviewPayload } from '../services/api';
import { 
  Play, 

  RotateCcw, 
  Activity, 
  LayoutGrid, 

  Monitor
} from 'lucide-react';
import { clsx } from 'clsx';

const nodeTypes = { 
  agent: AgentNode as any, 
} as const;

const initialNodes: Node[] = [
  // Input Node
  { id: 'DataCollector', type: 'agent', data: { label: '数据采集器', id: 'DataCollector' }, position: { x: 300, y: 0 } },
  
  // Analysts
  { id: 'FundamentalAnalyst', type: 'agent', data: { label: '基本面分析员', id: 'FundamentalAnalyst' }, position: { x: 0, y: 150 } },
  { id: 'TechnicalAnalyst', type: 'agent', data: { label: '技术面分析员', id: 'TechnicalAnalyst' }, position: { x: 200, y: 150 } },
  { id: 'NewsAnalyst', type: 'agent', data: { label: '新闻分析员', id: 'NewsAnalyst' }, position: { x: 400, y: 150 } },
  { id: 'SentimentAnalyst', type: 'agent', data: { label: '情绪分析员', id: 'SentimentAnalyst' }, position: { x: 600, y: 150 } },
  
  // Debate & Researcher
  { id: 'DebateResearcher', type: 'agent', data: { label: '辩论研究员', id: 'DebateResearcher' }, position: { x: 300, y: 300 } },
  
  // Decision
  { id: 'TraderDecision', type: 'agent', data: { label: '交易决策者', id: 'TraderDecision' }, position: { x: 300, y: 450 } },
  
  // Risk
  { id: 'RiskGuard', type: 'agent', data: { label: '风控守卫', id: 'RiskGuard' }, position: { x: 300, y: 600 } },
  
  // Output
  { id: 'ExecutionOutput', type: 'agent', data: { label: '执行输出', id: 'ExecutionOutput' }, position: { x: 300, y: 750 } },
];

const initialEdges: Edge[] = [
  // DataCollector -> Analysts
  { id: 'e1-1', source: 'DataCollector', target: 'FundamentalAnalyst', animated: true },
  { id: 'e1-2', source: 'DataCollector', target: 'TechnicalAnalyst', animated: true },
  { id: 'e1-3', source: 'DataCollector', target: 'NewsAnalyst', animated: true },
  { id: 'e1-4', source: 'DataCollector', target: 'SentimentAnalyst', animated: true },
  
  // Analysts -> Debate
  { id: 'e2-1', source: 'FundamentalAnalyst', target: 'DebateResearcher' },
  { id: 'e2-2', source: 'TechnicalAnalyst', target: 'DebateResearcher' },
  { id: 'e2-3', source: 'NewsAnalyst', target: 'DebateResearcher' },
  { id: 'e2-4', source: 'SentimentAnalyst', target: 'DebateResearcher' },
  
  // Debate -> Trader
  { id: 'e3', source: 'DebateResearcher', target: 'TraderDecision', animated: true },
  
  // Trader -> Risk
  { id: 'e4', source: 'TraderDecision', target: 'RiskGuard', animated: true },
  
  // Risk -> Execution
  { id: 'e5', source: 'RiskGuard', target: 'ExecutionOutput', animated: true },
].map(edge => ({
  ...edge,
  style: { stroke: '#00f0ff', strokeWidth: 1.5, opacity: 0.6 },
  markerEnd: { type: MarkerType.ArrowClosed, color: '#00f0ff' },
}));

const toOptionalNumber = (value: unknown): number | null => {
  if (value === null || value === undefined) {
    return null;
  }
  if (typeof value === 'string' && value.trim() === '') {
    return null;
  }
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
};

const toTimestamp = (value: unknown): number | null => {
  const num = toOptionalNumber(value);
  if (num === null || num <= 0) {
    return null;
  }
  return num > 1_000_000_000_000 ? num : num * 1000;
};

const resolveWorkshopNodeId = (type: unknown, message: unknown, payload: unknown): string | null => {
  const source = `${String(type ?? '')} ${String(message ?? '')}`.toLowerCase();
  const payloadText = payload && typeof payload === 'object' ? JSON.stringify(payload).toLowerCase() : '';
  const text = `${source} ${payloadText}`;

  if (text.includes('fundamental') || text.includes('基本面')) {
    return 'FundamentalAnalyst';
  }
  if (text.includes('technical') || text.includes('技术')) {
    return 'TechnicalAnalyst';
  }
  if (text.includes('news') || text.includes('新闻')) {
    return 'NewsAnalyst';
  }
  if (text.includes('sentiment') || text.includes('情绪')) {
    return 'SentimentAnalyst';
  }
  if (text.includes('debate') || text.includes('research') || text.includes('辩论')) {
    return 'DebateResearcher';
  }
  if (text.includes('risk') || text.includes('风控')) {
    return 'RiskGuard';
  }
  if (
    text.includes('trade') ||
    text.includes('order') ||
    text.includes('execution') ||
    text.includes('下单') ||
    text.includes('成交')
  ) {
    return text.includes('成交') || text.includes('filled') ? 'ExecutionOutput' : 'TraderDecision';
  }
  if (text.includes('collect') || text.includes('market') || text.includes('行情') || text.includes('data') || text.includes('数据')) {
    return 'DataCollector';
  }
  return null;
};

const resolveWorkshopLogType = (type: unknown, message: unknown): 'input' | 'output' | 'info' => {
  const text = `${String(type ?? '')} ${String(message ?? '')}`.toLowerCase();
  if (text.includes('collect') || text.includes('data') || text.includes('行情') || text.includes('输入')) {
    return 'input';
  }
  if (text.includes('trade') || text.includes('order') || text.includes('execution') || text.includes('输出') || text.includes('成交')) {
    return 'output';
  }
  return 'info';
};

const resolveWorkshopNodeStatus = (severity: unknown, message: unknown): AgentStatus => {
  const sev = String(severity ?? '').trim().toLowerCase();
  const msg = String(message ?? '').trim().toLowerCase();
  if (sev === 'high' || msg.includes('error') || msg.includes('failed') || msg.includes('拒单') || msg.includes('失败')) {
    return 'error';
  }
  if (msg.includes('pending') || msg.includes('running') || msg.includes('processing') || msg.includes('执行中')) {
    return 'thinking';
  }
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

  const onNodeClick = useCallback((_event: MouseEvent, node: Node) => {
    setSelectedNodeId(node.id);
  }, []);

  const selectedNodeLogs = useMemo(() => 
    logs.filter(log => log.nodeId === (selectedNodeId || activeNodeId)),
    [logs, selectedNodeId, activeNodeId]
  );

  const activeAgentCount = useMemo(
    () => Object.values(agents).filter((item) => item.status === 'thinking').length,
    [agents],
  );

  const latestUpdateText = useMemo(() => {
    const timestamps = Object.values(agents)
      .map((item) => toOptionalNumber(item.lastUpdate))
      .filter((item): item is number => item !== null && Number.isFinite(item) && item > 0);
    if (timestamps.length === 0) {
      return '--';
    }
    return new Date(Math.max(...timestamps)).toLocaleTimeString();
  }, [agents]);

  const hydrateFromAuditLogs = useCallback(async () => {
    const payload = await monitorApi.getAuditLogs<Array<Record<string, unknown>>>(80);
    const rows = Array.isArray(payload) ? payload : [];
    if (rows.length === 0) {
      return;
    }

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
          type: resolveWorkshopLogType(item.type, message),
          message,
        });
      });
    if (latestNode) {
      setActiveNode(latestNode);
    }
  }, [addLog, clearLogs, setActiveNode, updateAgentStatus]);

  const bootstrapWorkshop = useCallback(async () => {
    try {
      const overviewPayload = await monitorApi.getOverview<MonitorOverviewPayload>();
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

  useEffect(() => {
    void bootstrapWorkshop();
  }, [bootstrapWorkshop]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void bootstrapWorkshop();
    }, 12000);
    return () => window.clearInterval(timer);
  }, [bootstrapWorkshop]);

  return (
    <div className="flex h-[calc(100vh-80px)] w-full overflow-hidden bg-bg-primary">
      {/* Workflow Canvas */}
      <div className="relative flex-1 h-full border-r border-border/50 shadow-[inset_0_0_50px_rgba(0,0,0,0.5)]">
        <div className="absolute top-4 left-6 z-10 flex items-center gap-2 px-3 py-1.5 rounded-full bg-bg-card/80 border border-border backdrop-blur-md">
          <Activity className="w-4 h-4 text-neon-cyan" />
          <span className="text-xs font-mono font-bold tracking-[0.2em] text-neon-cyan">LANGGRAPH 引擎 v1.2</span>
          <span className="mx-2 w-px h-3 bg-border" />
          <div className="flex items-center gap-1.5">
            <div className="w-1.5 h-1.5 rounded-full bg-up-green shadow-[0_0_8px_#00ff9d] animate-pulse" />
            <span className="text-[10px] text-info-gray uppercase tracking-wider">实时流已激活</span>
          </div>
        </div>

        <ReactFlow
          nodes={initialNodes}
          edges={initialEdges}
          nodeTypes={nodeTypes}
          onNodeClick={onNodeClick}
          fitView
          className="react-flow-cyberpunk"
        >
          <Background color="#1e293b" gap={20} size={1} />
          <Controls className="bg-bg-card border-border !fill-info-gray" />
          
          <Panel position="top-right" className="bg-bg-card/90 border border-border p-2 rounded-lg backdrop-blur-md flex flex-col gap-2">
            <button 
              onClick={() => setSelectedNodeId(activeNodeId)}
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
                "text-2xl font-bold font-mono tracking-tighter font-orbitron",
                !hasPnlSnapshot
                  ? "text-info-gray/70"
                  : pnl >= 0
                    ? "text-up-green shadow-[0_0_20px_rgba(0,255,157,0.1)]"
                    : "text-down-red"
              )}>
                {hasPnlSnapshot ? `${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)} USD` : '--'}
              </div>
            </div>
          </Panel>
        </ReactFlow>
      </div>

      {/* Right Sidebar - Node Inspection */}
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

        {/* Trace Logs */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4 custom-scrollbar">
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
                      <span className="text-[9px] px-1 bg-bg-card text-info-gray rounded uppercase">{log.type}</span>
                    </div>
                    <p className="text-[11px] text-info-gray leading-relaxed">{log.message}</p>
                  </div>
                ))}
              </div>
            ) : (
              <div className="h-40 flex flex-col items-center justify-center border-2 border-dashed border-border rounded-xl">
                <LayoutGrid className="w-8 h-8 text-border mb-2" />
                <p className="text-[10px] text-info-gray font-mono uppercase">等待日志...</p>
              </div>
            )}
          </div>
        </div>

        {/* Node Metrics */}
        <div className="p-4 border-t border-border bg-bg-primary/50 h-[180px]">
          <h3 className="text-[10px] font-bold text-info-gray uppercase tracking-widest mb-3">算力资源监控</h3>
          <div className="grid grid-cols-2 gap-3">
            <div className="p-3 bg-bg-card border border-border rounded">
              <span className="text-[9px] text-info-gray uppercase font-mono block mb-1">SSE 连接</span>
              <span className={clsx('text-sm font-bold font-mono', isConnected ? 'text-up-green' : 'text-down-red')}>
                {isConnected ? 'ONLINE' : 'OFFLINE'}
              </span>
            </div>
            <div className="p-3 bg-bg-card border border-border rounded">
              <span className="text-[9px] text-info-gray uppercase font-mono block mb-1">活跃节点</span>
              <span className="text-sm font-bold text-white font-mono">{activeAgentCount}/{initialNodes.length}</span>
            </div>
            <div className="p-3 bg-bg-card border border-border rounded">
              <span className="text-[9px] text-info-gray uppercase font-mono block mb-1">日志缓存</span>
              <span className="text-sm font-bold text-up-green font-mono">{logs.length}</span>
            </div>
            <div className="p-3 bg-bg-card border border-border rounded">
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
