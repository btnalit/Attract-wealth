import { useEffect, useRef, useState } from 'react';
import { useAgentStore, AgentStatus, AgentLog } from '../store/agentStore';
import { streamApi } from '../services/api';

/** Raw payload from the backend SSE stream */
interface RawSSEPayload {
  type: string;
  timestamp: number;
  data: Record<string, unknown>;
}

export const useSSE = (enabled: boolean = true) => {
  const { updateAgentStatus, setActiveNode, addLog, updatePnl } = useAgentStore();
  const [isConnected, setIsConnected] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);

  /** Normalize snake_case from backend → camelCase for the store */
  function mapNodeId(raw: Record<string, unknown>): string | undefined {
    return (raw.nodeId ?? raw.node_id ?? raw.agent ?? raw.agent_name) as string | undefined;
  }

  /** 将后端状态统一映射到前端 AgentStatus 枚举。 */
  function normalizeAgentStatus(value: unknown, fallback: AgentStatus = 'idle'): AgentStatus {
    const status = String(value ?? '').trim().toLowerCase();
    if (!status) {
      return fallback;
    }
    if (['thinking', 'running', 'active', 'start', 'started'].includes(status)) {
      return 'thinking';
    }
    if (['success', 'completed', 'done', 'end', 'ended', 'ok'].includes(status)) {
      return 'success';
    }
    if (['error', 'failed', 'rejected', 'fatal'].includes(status)) {
      return 'error';
    }
    return fallback;
  }

  useEffect(() => {
    if (!enabled) return;

    const connect = () => {
      try {
        const url = streamApi.getEventsUrl();
        console.log(`Connecting to SSE at ${url}...`);

        const es = new EventSource(url);
        eventSourceRef.current = es;

        es.onopen = () => {
          console.log('SSE Connection established.');
          setIsConnected(true);
        };

        es.onmessage = (event) => {
          try {
            const raw: RawSSEPayload = JSON.parse(event.data);
            if (raw.type === 'ping') return;
            handleSSEEvent(raw);
          } catch (err) {
            console.error('Error parsing SSE data:', err);
          }
        };

        es.onerror = () => {
          console.warn('SSE Connection error. Switching to mock mode.');
          setIsConnected(false);
          es.close();
          // startMockMode(); // Mock mode can be triggered if desired
        };
      } catch (err) {
        console.error('SSE initialization error:', err);
      }
    };

    const handleSSEEvent = (raw: RawSSEPayload) => {
      const { type, data } = raw;
      const nodeId = mapNodeId(data);

      switch (type) {
        case 'agent_start':
          if (nodeId) updateAgentStatus(nodeId, 'thinking', data.ticker as string | undefined, 0);
          break;
        case 'agent_end': {
          const status = normalizeAgentStatus(data.status, 'success');
          if (nodeId) updateAgentStatus(nodeId, status, data.ticker as string | undefined, 100);
          break;
        }
        case 'node_transition':
          if (nodeId) {
            setActiveNode(nodeId);
            const status = normalizeAgentStatus(data.status, 'thinking');
            updateAgentStatus(nodeId, status, data.ticker as string | undefined, status === 'success' ? 100 : 50);
          }
          break;
        case 'log_message':
          if (data.message) {
            addLog({
              timestamp: new Date().toLocaleTimeString(),
              nodeId: nodeId || 'SYSTEM',
              type: (data.level as AgentLog['type']) || 'info',
              message: data.message as string,
            });
          }
          break;
        case 'trade_update':
          console.log('[SSE] Trade:', data);
          break;
        case 'pnl_update':
          if (typeof data.pnl === 'number') updatePnl(data.pnl);
          break;
        default:
          console.log('[SSE] Unhandled event:', type, data);
      }
    };

    connect();

    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, [enabled, updateAgentStatus, setActiveNode, addLog, updatePnl]);

  return { isConnected };
};
