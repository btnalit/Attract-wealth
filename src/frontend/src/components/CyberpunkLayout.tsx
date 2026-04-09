import React, { useState } from 'react';
import { Outlet, NavLink } from 'react-router-dom';
import { 
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
  Settings,
  Search,
  Bell,
  Wifi,
  Zap,
  Clock,
  Terminal
} from 'lucide-react';
import { cn } from '../lib/utils';
import { useHotkeys } from '../hooks/useHotkeys';
import { useSSE } from '../hooks/useSSE';
import { CommandPalette } from './CommandPalette';

const navItems = [
  { icon: LayoutDashboard, path: '/', label: '控制面板' },
  { icon: LineChart, path: '/market', label: '行情终端' },
  { icon: Cpu, path: '/agents', label: '智能体车间' },
  { icon: GitBranch, path: '/evolution', label: '进化中心' },
  { icon: Database, path: '/memory', label: '记忆库' },
  { icon: BookOpen, path: '/knowledge', label: '知识库' },
  { icon: Activity, path: '/execution', label: '执行监控' },
  { icon: Layers, path: '/strategies', label: '策略矩阵' },
  { icon: BarChart3, path: '/backtest', label: '回测实验室' },
  { icon: ShieldCheck, path: '/audit', label: '审计与风控' },
  { icon: Terminal, path: '/logs', label: '日志终端' },
  { icon: Settings, path: '/settings', label: '系统设置' },
];

export const CyberpunkLayout: React.FC = () => {
  const [isCommandPaletteOpen, setIsCommandPaletteOpen] = useState(false);

  useHotkeys(() => setIsCommandPaletteOpen(true));

  return (
    <div className="flex h-screen w-screen flex-col bg-bg-primary text-info-gray font-inter selection:bg-neon-cyan/30">
      {/* Scanline Effect Overlay */}
      <div className="scanline" />

      {/* Command Palette */}
      <CommandPalette 
        isOpen={isCommandPaletteOpen} 
        onClose={() => setIsCommandPaletteOpen(false)} 
      />
      
      {/* Top HUD Bar (50px) */}
      <header className="flex h-[50px] items-center justify-between border-b border-border bg-bg-card/80 px-4 backdrop-blur-md z-50">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <div className="h-6 w-6 bg-neon-cyan animate-pulse rounded-sm shadow-[0_0_10px_rgba(0,240,255,0.8)]" />
            <h1 className="font-orbitron text-xl font-extrabold tracking-tighter text-white">
              来财 <span className="text-neon-cyan text-xs font-normal tracking-widest ml-1">ATTRACT-WEALTH</span>
            </h1>
          </div>
          
          <button 
            onClick={() => setIsCommandPaletteOpen(true)}
            className="ml-8 flex h-8 items-center rounded-sm border border-border bg-bg-primary/50 px-3 transition-colors hover:border-neon-cyan/50 cursor-pointer group"
          >
            <Search className="h-4 w-4 text-info-gray group-hover:text-neon-cyan" />
            <span className="ml-2 text-xs text-info-gray/60 uppercase group-hover:text-info-gray">CMD+K 搜索...</span>
          </button>
        </div>

        <div className="flex items-center gap-6">
          <div className="flex gap-4 text-[10px] font-mono tracking-tighter uppercase">
            <div className="flex flex-col items-end">
              <span className="text-info-gray/50">CPU 负载</span>
              <span className="text-up-green">12.4%</span>
            </div>
            <div className="flex flex-col items-end border-l border-border pl-4">
              <span className="text-info-gray/50">内存使用</span>
              <span className="text-warn-gold">4.2 GB</span>
            </div>
            <div className="flex flex-col items-end border-l border-border pl-4">
              <span className="text-info-gray/50">运行中的智能体</span>
              <span className="text-neon-cyan">6 / 8</span>
            </div>
          </div>
          <div className="flex h-8 w-8 items-center justify-center rounded-sm border border-border hover:bg-bg-hover transition-colors cursor-pointer">
            <Bell className="h-4 w-4" />
          </div>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* Left Dock (64px expanded to 200px) */}
        <aside className="group/sidebar flex w-[64px] hover:w-[200px] flex-col items-start border-r border-border bg-bg-card/50 py-4 z-40 transition-all duration-300 overflow-y-auto custom-scrollbar overflow-x-hidden">
          <nav className="flex flex-col gap-2 w-full px-3">
            {navItems.map((item) => (
              <NavLink
                key={item.path}
                to={item.path}
                className={({ isActive }) => cn(
                  "group relative flex h-10 w-full items-center rounded-sm transition-all duration-300",
                  "hover:bg-neon-cyan/10 border border-transparent px-2",
                  isActive ? "border-neon-cyan/50 bg-neon-cyan/5 text-neon-cyan shadow-[0_0_15px_rgba(0,240,255,0.2)]" : "text-info-gray/60 hover:text-white"
                )}
              >
                {({ isActive }) => (
                  <>
                    <item.icon className="h-5 w-5 min-w-[24px]" />
                    <span className="ml-3 text-xs font-medium tracking-wider opacity-0 group-hover/sidebar:opacity-100 transition-opacity duration-300 whitespace-nowrap overflow-hidden">
                      {item.label}
                    </span>
                    {isActive && (
                      <div className="absolute -left-3 h-6 w-1 rounded-r-full bg-neon-cyan shadow-[0_0_10px_rgba(0,240,255,1)]" />
                    )}
                  </>
                )}
              </NavLink>
            ))}
          </nav>
        </aside>

        {/* Main Content Area */}
        <main className="relative flex-1 overflow-y-auto custom-scrollbar bg-[radial-gradient(circle_at_center,_var(--bg-hover)_0%,_var(--bg-primary)_100%)]">
          <Outlet />
        </main>
      </div>

      {/* Bottom Status Bar (28px) */}
      <footer className="flex h-[28px] items-center justify-between border-t border-border bg-bg-card px-4 text-[10px] font-mono z-50 uppercase">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-1.5">
            <div className="h-2 w-2 rounded-full bg-up-green shadow-[0_0_5px_rgba(0,255,157,0.8)]" />
            <span className="text-info-gray/80">API: 已连接</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="h-2 w-2 rounded-full bg-up-green shadow-[0_0_5px_rgba(0,255,157,0.8)] animate-pulse" />
            <span className="text-info-gray/80">WS: 推流中</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="h-2 w-2 rounded-full bg-neon-cyan shadow-[0_0_5px_rgba(0,240,255,0.8)]" />
            <span className="text-info-gray/80">SSE: 已同步</span>
          </div>
          <div className="ml-4 flex items-center gap-1 text-info-gray/40">
            <Zap className="h-3 w-3" />
            <span>最后信号: 12ms</span>
          </div>
        </div>

        <div className="flex items-center gap-6 text-info-gray/60">
          <div className="flex items-center gap-2">
            <Wifi className="h-3 w-3 text-up-green" />
            <span>YC-CLUSTER-A1</span>
          </div>
          <div className="flex items-center gap-2">
            <Clock className="h-3 w-3" />
            <span>{new Date().toLocaleTimeString()}</span>
          </div>
        </div>
      </footer>
    </div>
  );
};

export default CyberpunkLayout;
