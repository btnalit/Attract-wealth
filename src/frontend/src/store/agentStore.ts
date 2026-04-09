import { create } from 'zustand';

export type AgentStatus = 'idle' | 'thinking' | 'success' | 'error';

export interface AgentLog {
  timestamp: string;
  nodeId: string;
  type: 'input' | 'output' | 'info';
  message: string;
}

export interface NodeState {
  id: string;
  status: AgentStatus;
  ticker?: string;
  progress?: number;
  lastUpdate: number;
}

interface AgentState {
  agents: Record<string, NodeState>;
  activeNodeId: string | null;
  logs: AgentLog[];
  pnl: number;
  
  // Actions
  updateAgentStatus: (nodeId: string, status: AgentStatus, ticker?: string, progress?: number) => void;
  setActiveNode: (nodeId: string | null) => void;
  addLog: (log: AgentLog) => void;
  clearLogs: () => void;
  updatePnl: (pnl: number) => void;
  resetGraph: () => void;
}

export const useAgentStore = create<AgentState>((set) => ({
  agents: {},
  activeNodeId: null,
  logs: [],
  pnl: 0,

  updateAgentStatus: (nodeId, status, ticker, progress) => 
    set((state) => ({
      agents: {
        ...state.agents,
        [nodeId]: {
          id: nodeId,
          status,
          ticker: ticker || state.agents[nodeId]?.ticker,
          progress: progress !== undefined ? progress : state.agents[nodeId]?.progress,
          lastUpdate: Date.now(),
        },
      },
    })),

  setActiveNode: (nodeId) => set({ activeNodeId: nodeId }),

  addLog: (log) => set((state) => ({ 
    logs: [log, ...state.logs].slice(0, 100) // Keep last 100 logs
  })),

  clearLogs: () => set({ logs: [] }),

  updatePnl: (pnl) => set({ pnl }),

  resetGraph: () => set({
    agents: {},
    activeNodeId: null,
    logs: [],
  }),
}));
