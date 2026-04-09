import React, { memo } from 'react';
import { Handle, Position, NodeProps } from '@xyflow/react';
import { useAgentStore, AgentStatus } from '../store/agentStore';
import { Terminal, Activity, CheckCircle, AlertCircle, Loader2 } from 'lucide-react';
import { clsx } from 'clsx';

export type NodeData = {
  label: string;
  icon?: string;
  id: string;
};

const StatusIcon = ({ status }: { status?: AgentStatus }) => {
  switch (status) {
    case 'thinking':
      return <Loader2 className="w-4 h-4 animate-spin text-neon-cyan" />;
    case 'success':
      return <CheckCircle className="w-4 h-4 text-up-green" />;
    case 'error':
      return <AlertCircle className="w-4 h-4 text-down-red" />;
    default:
      return <Activity className="w-4 h-4 text-info-gray" />;
  }
};

const AgentNode = ({ data, isConnectable }: NodeProps<NodeData>) => {
  const { agents, activeNodeId } = useAgentStore();
  const agentState = agents[data.id];
  const isActive = activeNodeId === data.id;
  const status = agentState?.status || 'idle';

  return (
    <div className={clsx(
      "relative min-w-[180px] p-4 rounded-lg border-2 bg-bg-card/90 backdrop-blur-md transition-all duration-300",
      isActive ? "border-neon-cyan shadow-[0_0_20px_rgba(0,240,255,0.4)] scale-105" : "border-border",
      status === 'thinking' && "border-neon-cyan/50 shadow-[0_0_15px_rgba(0,240,255,0.2)] animate-pulse",
      status === 'success' && "border-up-green/50 shadow-[0_0_15px_rgba(0,255,157,0.2)]",
      status === 'error' && "border-down-red/50 shadow-[0_0_15px_rgba(255,0,85,0.2)]"
    )}>
      {/* Target/Source Handles */}
      <Handle type="target" position={Position.Top} isConnectable={isConnectable} className="!bg-neon-cyan/50" />
      <Handle type="source" position={Position.Bottom} isConnectable={isConnectable} className="!bg-neon-cyan/50" />

      {/* Cyberpunk Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <div className={clsx(
            "p-1.5 rounded-md",
            isActive ? "bg-neon-cyan/20" : "bg-bg-hover"
          )}>
            <Terminal className={clsx("w-4 h-4", isActive ? "text-neon-cyan" : "text-info-gray")} />
          </div>
          <span className="text-sm font-bold tracking-wider text-white uppercase font-orbitron">{data.label}</span>
        </div>
        <StatusIcon status={status} />
      </div>

      {/* Node Content */}
      <div className="space-y-2">
        <div className="flex justify-between text-[10px] text-info-gray uppercase font-mono">
          <span>{agentState?.ticker || '---'}</span>
          <span>{status}</span>
        </div>

        {/* Progress Bar */}
        <div className="w-full h-1.5 bg-bg-primary rounded-full overflow-hidden">
          <div 
            className={clsx(
              "h-full transition-all duration-500",
              status === 'thinking' ? "bg-neon-cyan shadow-[0_0_8px_#00f0ff]" : 
              status === 'success' ? "bg-up-green" : 
              status === 'error' ? "bg-down-red" : "bg-bg-hover"
            )}
            style={{ width: `${agentState?.progress || 0}%` }}
          />
        </div>
      </div>

      {/* Glowing Indicator for active state */}
      {isActive && (
        <div className="absolute inset-0 rounded-lg pointer-events-none ring-1 ring-inset ring-neon-cyan opacity-50 shadow-[0_0_15px_#00f0ff_inset]" />
      )}
    </div>
  );
};

export default memo(AgentNode);
