import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { 
  Search, 
  LayoutDashboard, 
  LineChart, 
  Cpu, 
  GitBranch, 
  Database, 
  BookOpen, 
  Activity, 
  Layers, 
  BarChart3, 
  ShieldCheck, 
  Terminal, 
  Settings,
  Play,
  Square,
  RefreshCw,
  Trash2
} from 'lucide-react';
import { cn } from '../lib/utils';

interface Command {
  id: string;
  label: string;
  category: string;
  icon: React.ElementType;
  action: () => void;
  shortcut?: string;
}

interface CommandPaletteProps {
  isOpen: boolean;
  onClose: () => void;
}

export const CommandPalette: React.FC<CommandPaletteProps> = ({ isOpen, onClose }) => {
  const [query, setQuery] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);

  const commands: Command[] = [
    // Navigation
    { id: 'nav-dashboard', label: '跳转到控制面板', category: '导航', icon: LayoutDashboard, action: () => navigate('/') },
    { id: 'nav-market', label: '跳转到行情终端', category: '导航', icon: LineChart, action: () => navigate('/market') },
    { id: 'nav-agents', label: '跳转到智能体车间', category: '导航', icon: Cpu, action: () => navigate('/agents') },
    { id: 'nav-evolution', label: '跳转到演进中心', category: '导航', icon: GitBranch, action: () => navigate('/evolution') },
    { id: 'nav-memory', label: '跳转到记忆金库', category: '导航', icon: Database, action: () => navigate('/memory') },
    { id: 'nav-knowledge', label: '跳转到知识库', category: '导航', icon: BookOpen, action: () => navigate('/knowledge') },
    { id: 'nav-execution', label: '跳转到执行监控', category: '导航', icon: Activity, action: () => navigate('/execution') },
    { id: 'nav-strategies', label: '跳转到策略矩阵', category: '导航', icon: Layers, action: () => navigate('/strategies') },
    { id: 'nav-backtest', label: '跳转到回测实验室', category: '导航', icon: BarChart3, action: () => navigate('/backtest') },
    { id: 'nav-audit', label: '跳转到审计与风控', category: '导航', icon: ShieldCheck, action: () => navigate('/audit') },
    { id: 'nav-logs', label: '跳转到日志终端', category: '导航', icon: Terminal, action: () => navigate('/logs') },
    { id: 'nav-settings', label: '跳转到系统设置', category: '导航', icon: Settings, action: () => navigate('/settings') },
    
    // Actions
    { id: 'action-start', label: '启动交易系统', category: '操作', icon: Play, action: () => console.log('Start Trading') },
    { id: 'action-stop', label: '停止交易系统', category: '操作', icon: Square, action: () => console.log('Stop Trading') },
    { id: 'action-reflect', label: '触发自我反思', category: '操作', icon: RefreshCw, action: () => console.log('Trigger Reflection') },
    { id: 'action-clear', label: '清空终端日志', category: '操作', icon: Trash2, action: () => console.log('Clear Logs') },
  ];

  const filteredCommands = commands.filter(cmd => 
    cmd.label.toLowerCase().includes(query.toLowerCase()) || 
    cmd.category.toLowerCase().includes(query.toLowerCase())
  );

  useEffect(() => {
    if (isOpen) {
      setQuery('');
      setActiveIndex(0);
      setTimeout(() => inputRef.current?.focus(), 10);
    }
  }, [isOpen]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!isOpen) return;
      
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setActiveIndex(prev => (prev + 1) % filteredCommands.length);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setActiveIndex(prev => (prev - 1 + filteredCommands.length) % filteredCommands.length);
      } else if (e.key === 'Enter') {
        if (filteredCommands[activeIndex]) {
          filteredCommands[activeIndex].action();
          onClose();
        }
      } else if (e.key === 'Escape') {
        onClose();
      }
    };
    
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, activeIndex, filteredCommands, onClose]);

  if (!isOpen) return null;

  return (
    <div 
      className="fixed inset-0 z-[100] flex items-start justify-center pt-[15vh] px-4 backdrop-blur-md bg-black/60"
      onClick={onClose}
    >
      <div 
        className="w-full max-w-2xl overflow-hidden rounded-md border border-neon-cyan/50 bg-bg-card/95 shadow-[0_0_30px_rgba(0,240,255,0.2)] animate-in fade-in zoom-in duration-200"
        onClick={e => e.stopPropagation()}
      >
        {/* Search Bar */}
        <div className="flex items-center border-b border-border p-4">
          <Search className="h-5 w-5 text-neon-cyan animate-pulse" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={e => setQuery(e.target.value)}
            className="flex-1 bg-transparent px-4 py-1 text-lg text-white outline-none placeholder:text-info-gray/40 font-orbitron"
            placeholder="输入指令或进行搜索..."
          />
          <kbd className="hidden sm:flex h-6 items-center gap-1 rounded border border-border bg-bg-primary px-1.5 font-mono text-[10px] text-info-gray/60 uppercase">
            ESC
          </kbd>
        </div>

        {/* Results */}
        <div className="max-h-[400px] overflow-y-auto custom-scrollbar p-2">
          {filteredCommands.length > 0 ? (
            <div className="space-y-4">
              {['导航', '操作'].map(category => {
                const categoryCommands = filteredCommands.filter(cmd => cmd.category === category);
                if (categoryCommands.length === 0) return null;
                
                return (
                  <div key={category}>
                    <div className="px-3 pb-2 pt-1 text-[10px] font-bold uppercase tracking-widest text-info-gray/40">
                      {category}
                    </div>
                    <div className="space-y-1">
                      {categoryCommands.map((cmd) => {
                        const globalIndex = filteredCommands.findIndex(c => c.id === cmd.id);
                        const isActive = globalIndex === activeIndex;
                        
                        return (
                          <div
                            key={cmd.id}
                            className={cn(
                              "flex items-center gap-3 rounded px-3 py-2 cursor-pointer transition-all duration-200",
                              isActive ? "bg-neon-cyan/20 border-l-4 border-neon-cyan text-white translate-x-1" : "text-info-gray/80 hover:bg-bg-hover hover:text-white"
                            )}
                            onMouseEnter={() => setActiveIndex(globalIndex)}
                            onClick={() => {
                              cmd.action();
                              onClose();
                            }}
                          >
                            <cmd.icon className={cn("h-4 w-4", isActive ? "text-neon-cyan" : "text-info-gray/60")} />
                            <span className="flex-1 text-sm font-medium">{cmd.label}</span>
                            {isActive && (
                              <span className="text-[10px] font-mono text-neon-cyan/60">ENTER</span>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <div className="mb-4 h-12 w-12 rounded-full bg-bg-hover flex items-center justify-center">
                <Search className="h-6 w-6 text-info-gray/40" />
              </div>
              <p className="text-info-gray/60">未找到指令 "{query}"</p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-border bg-bg-primary/50 px-4 py-2 text-[10px] text-info-gray/40 font-mono">
          <div className="flex gap-3">
            <span className="flex items-center gap-1">
              <kbd className="rounded border border-border bg-bg-card px-1">↓↑</kbd> 导航
            </span>
            <span className="flex items-center gap-1">
              <kbd className="rounded border border-border bg-bg-card px-1">ENTER</kbd> 执行
            </span>
          </div>
          <span>来财 命令控制台 V1.0</span>
        </div>
      </div>
    </div>
  );
};
