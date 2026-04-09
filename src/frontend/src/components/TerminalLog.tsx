import React, { useState, useEffect, useRef, useMemo } from 'react';
import { Search, Download, Trash2, Anchor, Filter } from 'lucide-react';
import { cn } from '../lib/utils';

export interface LogEntry {
  id: string;
  timestamp: string;
  agent: 'Collector' | 'Analyst' | 'Trader' | 'Risk' | 'System';
  level: 'info' | 'warn' | 'error' | 'debug';
  message: string;
  payload?: any;
}

interface TerminalLogProps {
  logs: LogEntry[];
  onClear?: () => void;
  className?: string;
}

const AGENT_COLORS: Record<LogEntry['agent'], string> = {
  Collector: 'text-neon-cyan',
  Analyst: 'text-neon-magenta',
  Trader: 'text-up-green',
  Risk: 'text-down-red',
  System: 'text-white',
};

export const TerminalLog: React.FC<TerminalLogProps> = ({ logs, onClear, className }) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [autoScroll, setAutoScroll] = useState(true);
  const [filterAgent, setFilterAgent] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const filteredLogs = useMemo(() => {
    return logs.filter(log => {
      const matchesSearch = log.message.toLowerCase().includes(searchTerm.toLowerCase()) || 
                           log.agent.toLowerCase().includes(searchTerm.toLowerCase());
      const matchesAgent = filterAgent ? log.agent === filterAgent : true;
      return matchesSearch && matchesAgent;
    });
  }, [logs, searchTerm, filterAgent]);

  // Simple "Virtualization": Only render the last 500 logs for performance
  const displayLogs = useMemo(() => filteredLogs.slice(-500), [filteredLogs]);

  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [displayLogs, autoScroll]);

  const handleExport = () => {
    const content = filteredLogs.map(l => `[${l.timestamp}] [${l.agent}] [${l.level.toUpperCase()}] ${l.message}`).join('\n');
    const blob = new Blob([content], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `terminal_logs_${new Date().toISOString()}.log`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className={cn("flex flex-col h-full bg-bg-primary border border-border rounded-sm overflow-hidden font-mono text-xs", className)}>
      {/* Terminal Toolbar */}
      <div className="flex items-center justify-between px-3 py-2 bg-bg-card border-b border-border">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2 bg-bg-primary px-2 py-1 rounded border border-border">
            <Search className="h-3 w-3 text-info-gray" />
            <input 
              type="text" 
              placeholder="GREP FILTER..." 
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="bg-transparent border-none outline-none text-white w-48 placeholder:text-info-gray/30"
            />
          </div>
          <div className="flex gap-2">
            {(['Collector', 'Analyst', 'Trader', 'Risk', 'System'] as const).map(agent => (
              <button 
                key={agent}
                onClick={() => setFilterAgent(filterAgent === agent ? null : agent)}
                className={cn(
                  "px-2 py-0.5 rounded border transition-colors",
                  filterAgent === agent ? "bg-bg-hover border-neon-cyan text-neon-cyan" : "bg-bg-primary border-border text-info-gray hover:text-white"
                )}
              >
                {agent}
              </button>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button 
            onClick={() => setAutoScroll(!autoScroll)} 
            className={cn("p-1 rounded hover:bg-bg-hover transition-colors", autoScroll ? "text-neon-cyan" : "text-info-gray")}
            title="Auto-scroll"
          >
            <Anchor className="h-4 w-4" />
          </button>
          <button onClick={handleExport} className="p-1 rounded hover:bg-bg-hover text-info-gray transition-colors" title="Export">
            <Download className="h-4 w-4" />
          </button>
          <button onClick={onClear} className="p-1 rounded hover:bg-bg-hover text-down-red/70 transition-colors" title="Clear">
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Log Display Area */}
      <div 
        ref={scrollRef}
        className="flex-1 overflow-y-auto p-3 space-y-1 custom-scrollbar"
        onScroll={(e) => {
          const target = e.currentTarget;
          const isAtBottom = Math.abs(target.scrollHeight - target.clientHeight - target.scrollTop) < 10;
          if (autoScroll && !isAtBottom) setAutoScroll(false);
          if (!autoScroll && isAtBottom) setAutoScroll(true);
        }}
      >
        {displayLogs.length === 0 ? (
          <div className="text-info-gray/40 italic py-4">NO LOGS MATCHING CRITERIA...</div>
        ) : (
          displayLogs.map((log) => (
            <div key={log.id} className="flex gap-3 hover:bg-white/5 py-0.5 px-1 rounded transition-colors group">
              <span className="text-info-gray/40 shrink-0 select-none">[{log.timestamp}]</span>
              <span className={cn("shrink-0 font-bold w-20", AGENT_COLORS[log.agent])}>[{log.agent}]</span>
              <span className={cn(
                "shrink-0 w-12",
                log.level === 'error' ? 'text-down-red' : 
                log.level === 'warn' ? 'text-warn-gold' : 
                'text-info-gray/60'
              )}>
                {log.level.toUpperCase()}
              </span>
              <span className="text-white/90 break-all">{log.message}</span>
              {log.payload && (
                <span className="text-info-gray/30 opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer underline ml-auto">
                  JSON
                </span>
              )}
            </div>
          ))
        )}
      </div>

      {/* Terminal Footer Status */}
      <div className="px-3 py-1 bg-bg-card border-t border-border flex justify-between items-center text-[10px] text-info-gray/50">
        <div>TOTAL: {logs.length} | FILTERED: {filteredLogs.length} | DISPLAYING: {displayLogs.length}</div>
        <div className="flex gap-4">
          <span>LINE: {filteredLogs.length}</span>
          <span>UTF-8</span>
          <span className="text-neon-cyan animate-pulse">TERMINAL ACTIVE</span>
        </div>
      </div>
    </div>
  );
};
