import { useCallback, useEffect, useMemo, useState, type FC } from 'react';
import {
  AlertTriangle,
  ChevronRight,
  Cpu,
  Layers,
  LayoutGrid,
  Loader2,
  RefreshCw,
  ShieldCheck,
  Terminal,
  Zap,
} from 'lucide-react';
import { cn } from '../lib/utils';
import { TerminalLog, type LogEntry } from '../components/TerminalLog';
import { monitorApi } from '../services/api';

const AGENT_CATEGORIES: Array<{ label: string; value: LogEntry['agent'] }> = [
  { label: '数据采集', value: 'Collector' },
  { label: '分析员', value: 'Analyst' },
  { label: '交易者', value: 'Trader' },
  { label: '风控', value: 'Risk' },
  { label: '系统', value: 'System' },
];

const toNumber = (value: unknown, fallback = 0): number => {
  const num = Number(value);
  return Number.isFinite(num) ? num : fallback;
};

const toTimestamp = (value: unknown): number => {
  const num = toNumber(value, 0);
  if (num <= 0) {
    return 0;
  }
  return num > 1_000_000_000_000 ? num : num * 1000;
};

const normalizeLevel = (severity: unknown, type: unknown): LogEntry['level'] => {
  const sev = String(severity ?? '').trim().toLowerCase();
  if (sev === 'high') {
    return 'error';
  }
  if (sev === 'medium') {
    return 'warn';
  }

  const lowerType = String(type ?? '').toLowerCase();
  if (lowerType.includes('error') || lowerType.includes('fail')) {
    return 'error';
  }
  if (lowerType.includes('warn')) {
    return 'warn';
  }
  return 'info';
};

const resolveAgent = (type: unknown, message: unknown, payload: unknown): LogEntry['agent'] => {
  const source = `${String(type ?? '')} ${String(message ?? '')}`.toLowerCase();
  const payloadSource = payload && typeof payload === 'object' ? JSON.stringify(payload).toLowerCase() : '';
  const text = `${source} ${payloadSource}`;

  if (text.includes('risk') || text.includes('风控')) {
    return 'Risk';
  }
  if (text.includes('trade') || text.includes('order') || text.includes('execution') || text.includes('下单') || text.includes('成交')) {
    return 'Trader';
  }
  if (text.includes('collect') || text.includes('data') || text.includes('market') || text.includes('行情') || text.includes('数据')) {
    return 'Collector';
  }
  if (text.includes('analyst') || text.includes('analysis') || text.includes('strategy') || text.includes('signal') || text.includes('分析') || text.includes('策略')) {
    return 'Analyst';
  }
  return 'System';
};

const renderAgentIcon = (agent: LogEntry['agent']) => {
  if (agent === 'Collector') {
    return <Zap className="h-3.5 w-3.5" />;
  }
  if (agent === 'Analyst') {
    return <Layers className="h-3.5 w-3.5" />;
  }
  if (agent === 'Trader') {
    return <Terminal className="h-3.5 w-3.5" />;
  }
  if (agent === 'Risk') {
    return <ShieldCheck className="h-3.5 w-3.5" />;
  }
  return <Cpu className="h-3.5 w-3.5" />;
};

const renderAgentDot = (agent: LogEntry['agent']) => {
  if (agent === 'Collector') {
    return 'bg-neon-cyan';
  }
  if (agent === 'Analyst') {
    return 'bg-neon-magenta';
  }
  if (agent === 'Trader') {
    return 'bg-up-green';
  }
  if (agent === 'Risk') {
    return 'bg-down-red';
  }
  return 'bg-white';
};

export const LogTerminal: FC = () => {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState('');
  const [activeAgent, setActiveAgent] = useState<LogEntry['agent'] | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);

  const fetchLogs = useCallback(async (silent = false) => {
    if (!silent) {
      setLoading(true);
    }
    setErrorMessage('');
    try {
      const payload = await monitorApi.getAuditLogs<Array<Record<string, unknown>>>(200);
      const rows = Array.isArray(payload) ? payload : [];
      const normalized = rows
        .map((item, index) => {
          const ts = toTimestamp(item.timestamp);
          const message = String(item.message ?? item.detail ?? '');
          const type = String(item.type ?? 'SYSTEM');
          const payloadObj =
            item.payload && typeof item.payload === 'object' ? (item.payload as Record<string, unknown>) : undefined;
          return {
            id: `AUD_${ts || Date.now()}_${index}_${type}`,
            timestamp: ts > 0 ? new Date(ts).toLocaleTimeString() : '--',
            agent: resolveAgent(type, message, payloadObj),
            level: normalizeLevel(item.severity, type),
            message: message || `${type} 事件`,
            payload: payloadObj,
            sortAt: ts,
          };
        })
        .sort((a, b) => a.sortAt - b.sortAt)
        .map(({ sortAt: _sortAt, ...rest }) => rest);
      setLogs(normalized);
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : '日志拉取失败。';
      setErrorMessage(errMsg);
      if (!silent) {
        setLogs([]);
      }
    } finally {
      if (!silent) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    void fetchLogs();
  }, [fetchLogs]);

  useEffect(() => {
    if (!autoRefresh) {
      return;
    }
    const timer = window.setInterval(() => {
      void fetchLogs(true);
    }, 6000);
    return () => window.clearInterval(timer);
  }, [autoRefresh, fetchLogs]);

  const filteredLogs = useMemo(
    () => (activeAgent ? logs.filter((log) => log.agent === activeAgent) : logs),
    [activeAgent, logs],
  );

  return (
    <div className="flex h-[calc(100vh-78px)] overflow-hidden bg-bg-primary">
      <aside className="w-64 border-r border-border bg-bg-card/30 flex flex-col z-10 p-4 space-y-6">
        <div>
          <h2 className="font-orbitron text-xs font-bold text-info-gray uppercase tracking-[0.2em] mb-4">智能体集群</h2>
          <nav className="space-y-2">
            <button
              onClick={() => setActiveAgent(null)}
              className={cn(
                'w-full flex items-center justify-between px-3 py-2 rounded-sm border transition-all text-xs font-mono',
                activeAgent === null
                  ? 'bg-neon-cyan/10 border-neon-cyan/50 text-neon-cyan shadow-[0_0_10px_rgba(0,240,255,0.1)]'
                  : 'bg-bg-primary/50 border-border/50 text-info-gray hover:text-white',
              )}
            >
              <div className="flex items-center gap-2">
                <LayoutGrid className="h-3.5 w-3.5" />
                <span>所有智能体</span>
              </div>
              <ChevronRight className="h-3 w-3" />
            </button>
            {AGENT_CATEGORIES.map((agent) => (
              <button
                key={agent.value}
                onClick={() => setActiveAgent(agent.value)}
                className={cn(
                  'w-full flex items-center justify-between px-3 py-2 rounded-sm border transition-all text-xs font-mono group',
                  activeAgent === agent.value
                    ? 'bg-neon-cyan/10 border-neon-cyan/50 text-neon-cyan shadow-[0_0_10px_rgba(0,240,255,0.1)]'
                    : 'bg-bg-primary/50 border-border/50 text-info-gray hover:text-white',
                )}
              >
                <div className="flex items-center gap-2">
                  {renderAgentIcon(agent.value)}
                  <span>{agent.label}</span>
                </div>
                <div className={cn('w-1.5 h-1.5 rounded-full animate-pulse', renderAgentDot(agent.value))} />
              </button>
            ))}
          </nav>
        </div>

        <div className="mt-auto pt-4 border-t border-border space-y-2">
          <button
            onClick={() => void fetchLogs()}
            disabled={loading}
            className="w-full flex items-center justify-center gap-2 py-2 border border-border hover:border-neon-cyan hover:text-neon-cyan text-[10px] font-bold uppercase transition-all rounded-sm disabled:opacity-60"
          >
            <RefreshCw className={cn('h-3 w-3', loading && 'animate-spin')} />
            手动刷新
          </button>
          <button
            onClick={() => setAutoRefresh((prev) => !prev)}
            className={cn(
              'w-full flex items-center justify-center gap-2 py-2 border text-[10px] font-bold uppercase transition-all rounded-sm',
              autoRefresh
                ? 'border-up-green/50 text-up-green hover:bg-up-green/10'
                : 'border-border text-info-gray hover:text-white',
            )}
          >
            <RefreshCw className="h-3 w-3" />
            {autoRefresh ? '自动刷新中' : '自动刷新关闭'}
          </button>
        </div>
      </aside>

      <main className="flex-1 flex flex-col min-w-0">
        <header className="h-12 border-b border-border bg-bg-card/50 flex items-center justify-between px-6">
          <div className="flex items-center gap-3">
            <Terminal className="h-4 w-4 text-neon-cyan" />
            <h1 className="font-orbitron text-sm font-bold tracking-[0.3em] uppercase text-white">分布式日志终端</h1>
          </div>
          <span className="text-[10px] text-info-gray/50 font-mono">source: /api/v1/monitor/audit</span>
        </header>

        {errorMessage && (
          <div className="mx-6 mt-4 px-3 py-2 text-xs rounded-sm border border-down-red/40 bg-down-red/10 text-down-red flex items-center gap-2">
            <AlertTriangle className="h-3.5 w-3.5" />
            {errorMessage}
          </div>
        )}

        <div className="flex-1 p-6 overflow-hidden">
          {loading && filteredLogs.length === 0 ? (
            <div className="h-full rounded-sm border border-border bg-bg-card/30 flex items-center justify-center text-info-gray/70 text-xs gap-2">
              <Loader2 className="h-4 w-4 animate-spin" />
              正在拉取审计日志...
            </div>
          ) : (
            <TerminalLog logs={filteredLogs} onClear={() => setLogs([])} className="shadow-[0_0_30px_rgba(0,0,0,0.5)] border-neon-cyan/20" />
          )}
        </div>
      </main>
    </div>
  );
};

export default LogTerminal;
