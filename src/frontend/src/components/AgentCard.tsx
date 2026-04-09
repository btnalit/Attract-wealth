import React from 'react';
import { useAgentStore } from '../store/agentStore';
import { clsx } from 'clsx';
import { Bot, Zap, Clock, ShieldCheck } from 'lucide-react';

interface AgentCardProps {
  id: string;
  name: string;
  description: string;
  role: string;
  avatarUrl?: string;
}

export const AgentCard: React.FC<AgentCardProps> = ({ id, name, description, role, avatarUrl }) => {
  const { agents } = useAgentStore();
  const agentState = agents[id];
  const status = agentState?.status || 'idle';

  const getStatusStyles = () => {
    switch (status) {
      case 'thinking':
        return "border-neon-cyan shadow-[0_0_15px_rgba(0,240,255,0.4)] animate-pulse";
      case 'success':
        return "border-up-green shadow-[0_0_15px_rgba(0,255,157,0.3)] bg-up-green/5";
      case 'error':
        return "border-down-red shadow-[0_0_20px_rgba(255,0,85,0.4)] animate-[flicker_0.5s_infinite_alternate]";
      default:
        return "border-border/50 bg-bg-card/20";
    }
  };

  const getStatusLabel = () => {
    switch (status) {
      case 'thinking': return 'Thinking...';
      case 'success': return 'Success';
      case 'error': return 'Error';
      default: return 'Idle';
    }
  };

  return (
    <div className={clsx(
      "group relative flex flex-col p-6 rounded-2xl border-2 bg-bg-card/40 backdrop-blur-xl transition-all duration-500 overflow-hidden min-h-[280px]",
      getStatusStyles()
    )}>
      {/* Background Glow */}
      <div className={clsx(
        "absolute -top-24 -right-24 w-48 h-48 rounded-full blur-[80px] opacity-20 transition-all duration-1000",
        status === 'thinking' && "bg-neon-cyan",
        status === 'success' && "bg-up-green",
        status === 'error' && "bg-down-red",
        status === 'idle' && "bg-info-gray"
      )} />

      {/* Header */}
      <div className="flex items-start justify-between mb-6 z-10">
        <div className="flex gap-4">
          <div className={clsx(
            "w-14 h-14 rounded-xl flex items-center justify-center border-2 transition-all duration-500",
            status === 'thinking' ? "bg-neon-cyan/20 border-neon-cyan shadow-[0_0_15px_rgba(0,240,255,0.3)]" : 
            status === 'success' ? "bg-up-green/20 border-up-green" :
            status === 'error' ? "bg-down-red/20 border-down-red" : "bg-bg-hover border-border"
          )}>
            {avatarUrl ? (
              <img src={avatarUrl} alt={name} className="w-full h-full rounded-lg object-cover" />
            ) : (
              <Bot className={clsx(
                "w-7 h-7",
                status === 'thinking' ? "text-neon-cyan" : 
                status === 'success' ? "text-up-green" : 
                status === 'error' ? "text-down-red" : "text-info-gray"
              )} />
            )}
          </div>
          <div>
            <h3 className="text-xl font-bold text-white tracking-tight font-orbitron">{name}</h3>
            <p className="text-[11px] text-info-gray/80 font-mono uppercase tracking-[0.15em] mt-0.5">{role}</p>
          </div>
        </div>
        
        {/* Pulse Indicator */}
        <div className="flex flex-col items-end gap-1.5">
          <div className={clsx(
            "px-2.5 py-1 rounded text-[10px] font-bold uppercase tracking-wider font-mono border",
            status === 'thinking' ? "text-neon-cyan border-neon-cyan/40 bg-neon-cyan/10" : 
            status === 'success' ? "text-up-green border-up-green/40 bg-up-green/10" : 
            status === 'error' ? "text-down-red border-down-red/40 bg-down-red/10" : "text-info-gray border-border bg-info-gray/5"
          )}>
            {getStatusLabel()}
          </div>
          {status === 'thinking' && (
            <div className="flex gap-0.5">
              <div className="w-1 h-1 rounded-full bg-neon-cyan animate-bounce [animation-delay:-0.3s]" />
              <div className="w-1 h-1 rounded-full bg-neon-cyan animate-bounce [animation-delay:-0.15s]" />
              <div className="w-1 h-1 rounded-full bg-neon-cyan animate-bounce" />
            </div>
          )}
        </div>
      </div>

      {/* Description */}
      <p className="text-sm text-info-gray leading-relaxed mb-6 flex-1 z-10">
        {description}
      </p>

      {/* Meta Stats */}
      <div className="flex items-center gap-6 pt-6 border-t border-border/50 z-10">
        <div className="flex items-center gap-2">
          <Zap className="w-3.5 h-3.5 text-warn-gold" />
          <span className="text-[10px] text-info-gray font-mono">POWER: 98%</span>
        </div>
        <div className="flex items-center gap-2">
          <Clock className="w-3.5 h-3.5 text-neon-cyan" />
          <span className="text-[10px] text-info-gray font-mono">TTL: 24h</span>
        </div>
        <div className="flex items-center gap-2">
          <ShieldCheck className="w-3.5 h-3.5 text-up-green" />
          <span className="text-[10px] text-info-gray font-mono">SECURED</span>
        </div>
      </div>
      
      {/* Decorative Corner */}
      <div className="absolute top-0 right-0 w-12 h-12">
        <div className="absolute top-0 right-0 w-full h-full bg-gradient-to-bl from-slate-700/20 to-transparent transform rotate-45 translate-x-1/2 -translate-y-1/2" />
      </div>
    </div>
  );
};

export default AgentCard;
