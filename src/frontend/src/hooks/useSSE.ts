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
  const [retryCount, setRetryCount] = useState(0);
  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const enabledRef = useRef(enabled);
  const attemptRef = useRef(0);

  // 同步 enabled 到 ref，避免重连闭包读到旧值
  useEffect(() => {
    enabledRef.current = enabled;
  }, [enabled]);

  /** 清理当前连接与待重连定时器 */
  const cleanup = () => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
  };

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

    const MAX_RETRIES = 10;
    const BASE_DELAY_MS = 1000;

    /** 计算指数退避延迟（带上限 30s） */
    const backoffDelay = (attempt: number): number =>
      Math.min(BASE_DELAY_MS * Math.pow(2, attempt), 30000);

    const connect = () => {
      if (!enabledRef.current) return;
      try {
        const url = streamApi.getEventsUrl();
        console.log(`Connecting to SSE at ${url}... (attempt ${attemptRef.current + 1})`);

        const es = new EventSource(url);
        eventSourceRef.current = es;

        es.onopen = () => {
          console.log('SSE Connection established.');
          setIsConnected(true);
          setRetryCount(0);
          attemptRef.current = 0;
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
          setIsConnected(false);
          es.close();
          eventSourceRef.current = null;

          // 指数退避自动重连（仅在仍启用且未超最大重试次数时）
          if (!enabledRef.current) return;
          if (attemptRef.current >= MAX_RETRIES) {
            console.error(`SSE max retries (${MAX_RETRIES}) reached, giving up. Page refresh required.`);
            return;
          }
          const delay = backoffDelay(attemptRef.current);
          attemptRef.current += 1;
          setRetryCount(attemptRef.current);
          console.warn(`SSE disconnected, reconnecting in ${delay}ms (attempt ${attemptRef.current}/${MAX_RETRIES})`);
          reconnectTimerRef.current = setTimeout(connect, delay);
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

    return cleanup;
  }, [enabled, updateAgentStatus, setActiveNode, addLog, updatePnl]);

  return { isConnected, retryCount };
};
