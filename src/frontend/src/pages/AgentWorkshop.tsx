import { useCallback, useMemo, useState, type MouseEvent } from 'react';
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
import { useAgentStore } from '../store/agentStore';
import { useSSE } from '../hooks/useSSE';
import AgentNode from '../components/AgentNode';
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

const AgentWorkshop = () => {
  useSSE(); // Activate SSE stream
  const { logs, activeNodeId, resetGraph, pnl } = useAgentStore();
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  const onNodeClick = useCallback((_event: MouseEvent, node: Node) => {
    setSelectedNodeId(node.id);
  }, []);

  const selectedNodeLogs = useMemo(() => 
    logs.filter(log => log.nodeId === (selectedNodeId || activeNodeId)),
    [logs, selectedNodeId, activeNodeId]
  );

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
              onClick={() => console.log('Start Run')}
              className="flex items-center gap-2 px-4 py-2 bg-neon-cyan/20 hover:bg-neon-cyan/30 text-neon-cyan rounded-md border border-neon-cyan/30 transition-all group"
            >
              <Play className="w-4 h-4 fill-neon-cyan group-hover:scale-110 transition-transform" />
              <span className="text-xs font-bold uppercase tracking-widest font-mono">运行工作流</span>
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
                pnl >= 0 ? "text-up-green shadow-[0_0_20px_rgba(0,255,157,0.1)]" : "text-down-red"
              )}>
                {pnl >= 0 ? '+' : ''}{pnl.toFixed(2)} USD
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
              <span className="text-[9px] text-info-gray uppercase font-mono block mb-1">推理耗时</span>
              <span className="text-sm font-bold text-white font-mono">1.2s</span>
            </div>
            <div className="p-3 bg-bg-card border border-border rounded">
              <span className="text-[9px] text-info-gray uppercase font-mono block mb-1">Token 消耗</span>
              <span className="text-sm font-bold text-white font-mono">4.2k</span>
            </div>
            <div className="p-3 bg-bg-card border border-border rounded">
              <span className="text-[9px] text-info-gray uppercase font-mono block mb-1">决策置信度</span>
              <span className="text-sm font-bold text-up-green font-mono">92%</span>
            </div>
            <div className="p-3 bg-bg-card border border-border rounded">
              <span className="text-[9px] text-info-gray uppercase font-mono block mb-1">异常重试</span>
              <span className="text-sm font-bold text-warn-gold font-mono">0</span>
            </div>
          </div>
        </div>
      </aside>
    </div>
  );
};

export default AgentWorkshop;
