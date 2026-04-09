import { useState, FC } from 'react';
import { 
  Terminal, 
  Trash2, 
  Cpu, 
  Layers, 
  ShieldCheck, 
  Zap,
  LayoutGrid,
  ChevronRight
} from 'lucide-react';
import { cn } from '../lib/utils';
import { TerminalLog } from '../components/TerminalLog';
import { useAgentStore } from '../store/agentStore';

const AGENTS = ['数据采集', '分析员', '交易者', '风控', '系统'] as const;

export const LogTerminal: FC = () => {
  const { logs, clearLogs } = useAgentStore();
  const [activeAgent, setActiveAgent] = useState<string | null>(null);

  // Map store nodeId to the side menu categories
  const mappedLogs = logs.map((l, i): any => ({
    id: `LOG_${i}`,
    timestamp: l.timestamp,
    agent: l.nodeId.includes('Analyst') ? '分析员' : 
           l.nodeId.includes('Collector') ? '数据采集' :
           l.nodeId.includes('Trader') ? '交易者' :
           l.nodeId.includes('Risk') ? '风控' : '系统',
    level: l.type === 'input' ? 'info' : (l.type === 'output' ? 'info' : l.type),
    message: l.message
  }));

  const filteredLogs = activeAgent 
    ? mappedLogs.filter((l: any) => l.agent === activeAgent) 
    : mappedLogs;

  return (
    <div className="flex h-[calc(100vh-78px)] overflow-hidden bg-bg-primary">
      {/* Sidebar: Role Filter */}
      <aside className="w-64 border-r border-border bg-bg-card/30 flex flex-col z-10 p-4 space-y-6">
        <div>
          <h2 className="font-orbitron text-xs font-bold text-info-gray uppercase tracking-[0.2em] mb-4">
            智能体集群
          </h2>
          <nav className="space-y-2">
            <button 
              onClick={() => setActiveAgent(null)}
              className={cn(
                "w-full flex items-center justify-between px-3 py-2 rounded-sm border transition-all text-xs font-mono",
                activeAgent === null ? "bg-neon-cyan/10 border-neon-cyan/50 text-neon-cyan shadow-[0_0_10px_rgba(0,240,255,0.1)]" : "bg-bg-primary/50 border-border/50 text-info-gray hover:text-white"
              )}
            >
              <div className="flex items-center gap-2">
                <LayoutGrid className="h-3.5 w-3.5" />
                <span>所有智能体</span>
              </div>
              <ChevronRight className="h-3 w-3" />
            </button>
            {AGENTS.map(agent => (
              <button 
                key={agent}
                onClick={() => setActiveAgent(agent)}
                className={cn(
                  "w-full flex items-center justify-between px-3 py-2 rounded-sm border transition-all text-xs font-mono group",
                  activeAgent === agent ? "bg-neon-cyan/10 border-neon-cyan/50 text-neon-cyan shadow-[0_0_10px_rgba(0,240,255,0.1)]" : "bg-bg-primary/50 border-border/50 text-info-gray hover:text-white"
                )}
              >
                <div className="flex items-center gap-2">
                  {agent === '数据采集' && <Zap className="h-3.5 w-3.5" />}
                  {agent === '分析员' && <Layers className="h-3.5 w-3.5" />}
                  {agent === '交易者' && <Terminal className="h-3.5 w-3.5" />}
                  {agent === '风控' && <ShieldCheck className="h-3.5 w-3.5" />}
                  {agent === '系统' && <Cpu className="h-3.5 w-3.5" />}
                  <span>{agent.toUpperCase()}</span>
                </div>
                <div className={cn(
                  "w-1.5 h-1.5 rounded-full animate-pulse",
                  agent === '数据采集' ? 'bg-neon-cyan' :
                  agent === '分析员' ? 'bg-neon-magenta' :
                  agent === '交易者' ? 'bg-up-green' :
                  agent === '风控' ? 'bg-down-red' : 'bg-white'
                )} />
              </button>
            ))}
          </nav>
        </div>

        <div className="mt-auto pt-4 border-t border-border">
          <button 
            onClick={clearLogs}
            className="w-full flex items-center justify-center gap-2 py-2 border border-border hover:border-down-red hover:text-down-red text-[10px] font-bold uppercase transition-all rounded-sm"
          >
            <Trash2 className="h-3 w-3" />
            清空日志缓存
          </button>
        </div>
      </aside>

      {/* Main Area: Log Terminal */}
      <main className="flex-1 flex flex-col min-w-0">
        <header className="h-12 border-b border-border bg-bg-card/50 flex items-center justify-between px-6">
          <div className="flex items-center gap-3">
            <Terminal className="h-4 w-4 text-neon-cyan" />
            <h1 className="font-orbitron text-sm font-bold tracking-[0.3em] uppercase text-white">
              分布式日志终端
              <span className="ml-3 text-info-gray/40 font-mono font-normal tracking-normal lowercase italic text-xs">
                (通过 SSE 实时推送)
              </span>
            </h1>
          </div>
        </header>
        
        <div className="flex-1 p-6 overflow-hidden">
          <TerminalLog 
            logs={filteredLogs} 
            onClear={clearLogs}
            className="shadow-[0_0_30px_rgba(0,0,0,0.5)] border-neon-cyan/20"
          />
        </div>
      </main>
    </div>
  );
};

export default LogTerminal;
