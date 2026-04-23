import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity,
  AlertOctagon,
  ArrowDownCircle,
  ArrowUpCircle,
  Ban,
  Clock,
  Cpu,
  ExternalLink,
  Loader2,
  RefreshCw,
  RotateCw,
  Wifi,
  WifiOff,
} from 'lucide-react';
import { cn } from '../lib/utils';
import { PageTitle } from '../components/PageTitle';
import {
  monitorApi,
  tradingApi,
  type ApiLooseObject,
  type MonitorStatusPayload,
  type TradingSnapshotChannelInfo,
  type TradingSnapshotOrderPayload,
  type TradingSnapshotPayload,
} from '../services/api';

interface Channel {
  id: string;
  name: string;
  status: string;
  latency: number;
  throughput: number;
  lastSync: string;
}

interface Order {
  id: string;
  symbol: string;
  name: string;
  side: string;
  price: number;
  qty: number;
  status: string;
  duration: string;
}

interface Fill {
  id: string;
  time: string;
  symbol: string;
  side: string;
  avgPrice: number;
  qty: number;
  status: string;
}

const STATUS_MAP: Record<string, { label: string; color: string }> = {
  PENDING: { label: '待报', color: 'text-info-gray/60 bg-info-gray/10 border-info-gray/20' },
  SUBMITTED: { label: '已报', color: 'text-neon-cyan bg-neon-cyan/10 border-neon-cyan/20' },
  PARTIAL: { label: '部成', color: 'text-warn-gold bg-warn-gold/10 border-warn-gold/20' },
  FILLED: { label: '已成', color: 'text-up-green bg-up-green/10 border-up-green/20' },
  CANCELED: { label: '已撤', color: 'text-down-red bg-down-red/10 border-down-red/20' },
  REJECTED: { label: '拒单', color: 'text-down-red bg-down-red/10 border-down-red/20' },
  FAILED: { label: '失败', color: 'text-down-red bg-down-red/10 border-down-red/20' },
};

const MOCK_CHANNELS: Channel[] = [
  { id: 'ths_ipc', name: 'THS IPC', status: 'offline', latency: 0, throughput: 0, lastSync: '--' },
  { id: 'simulator', name: 'Simulator', status: 'offline', latency: 0, throughput: 0, lastSync: '--' },
  { id: 'miniqmt', name: 'miniQMT', status: 'paused', latency: 0, throughput: 0, lastSync: '--' },
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

const formatClock = (value: unknown): string => {
  const ts = toTimestamp(value);
  if (ts <= 0) {
    return '--';
  }
  return new Date(ts).toLocaleTimeString();
};

const normalizeStatus = (value: unknown, fallback = 'PENDING'): string => {
  const status = String(value ?? '').trim().toUpperCase();
  return status || fallback;
};

const parsePayloadData = <T,>(payload: unknown): T => {
  if (payload && typeof payload === 'object' && 'data' in payload) {
    return (payload as { data: T }).data;
  }
  return payload as T;
};

const buildFillsFromSnapshotOrders = (orders: TradingSnapshotOrderPayload[]): Fill[] => {
  return orders
    .map((order, index) => {
      const status = normalizeStatus(order.status, 'SUBMITTED');
      const filledQty = toNumber(order.filled_quantity ?? order.filled_qty ?? order.quantity ?? order.qty, 0);
      const avgPrice = toNumber(order.filled_price ?? order.avg_price ?? order.price, 0);
      const side = normalizeStatus(order.side, 'BUY');
      const symbol = String(order.ticker ?? order.symbol ?? '--');
      const updatedAt = order.updated_at ?? order.update_time ?? order.timestamp ?? order.created_at ?? Date.now();

      return {
        id: String(order.order_id ?? order.id ?? `${symbol}-${index}`),
        time: formatClock(updatedAt),
        symbol,
        side,
        avgPrice,
        qty: filledQty,
        status,
        sortAt: toTimestamp(updatedAt),
      };
    })
    .filter((item) => item.qty > 0 && ['FILLED', 'PARTIAL', 'SUBMITTED'].includes(item.status))
    .sort((a, b) => b.sortAt - a.sortAt)
    .slice(0, 30)
    .map(({ sortAt: _sortAt, ...rest }) => rest);
};

export const ExecutionMonitor: React.FC = () => {
  const [channels, setChannels] = useState<Channel[]>(MOCK_CHANNELS);
  const [thsInfo, setThsInfo] = useState<TradingSnapshotChannelInfo | null>(null);
  const [orders, setOrders] = useState<Order[]>([]);
  const [fills, setFills] = useState<Fill[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncingOrders, setSyncingOrders] = useState(false);
  const [stoppingTrading, setStoppingTrading] = useState(false);
  const [switchingChannel, setSwitchingChannel] = useState(false);
  const [cancelingOrders, setCancelingOrders] = useState(false);
  const [actionMessage, setActionMessage] = useState<string>('');

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [statusResult, ordersResult, snapshotResult] = await Promise.allSettled([
        monitorApi.getStatus<MonitorStatusPayload[]>(),
        tradingApi.getActiveOrders(50),
        tradingApi.getSnapshot(),
      ]);

      if (statusResult.status === 'fulfilled') {
        const statusPayload = parsePayloadData<MonitorStatusPayload[]>(statusResult.value);
        if (Array.isArray(statusPayload)) {
          setChannels(
            statusPayload.map((item) => {
              const name = String(item.name ?? 'unknown');
              const status = String(item.status ?? 'offline').toLowerCase();
              return {
                id: name.toLowerCase().replace(/\s+/g, '_'),
                name,
                status,
                latency: Math.round(toNumber(item.latency_ms, 0)),
                throughput: Math.round(toNumber(item.throughput, 0)),
                lastSync: formatClock(item.last_sync),
              };
            }),
          );
        }
      }

      if (ordersResult.status === 'fulfilled') {
        const ordersPayload = parsePayloadData<ApiLooseObject[]>(ordersResult.value);
        if (Array.isArray(ordersPayload)) {
          setOrders(
            ordersPayload.map((item, index) => ({
              id: String(item.order_id ?? item.id ?? `ORD_${index}`),
              symbol: String(item.ticker ?? item.symbol ?? '--'),
              name: String(item.ticker ?? item.symbol ?? '--'),
              side: normalizeStatus(item.side, 'BUY'),
              price: toNumber(item.price, 0),
              qty: toNumber(item.quantity ?? item.qty, 0),
              status: normalizeStatus(item.status, 'PENDING'),
              duration: `${(toNumber(item.holding_time, 0) / 1000).toFixed(1)}s`,
            })),
          );
        } else {
          setOrders([]);
        }
      }

      if (snapshotResult.status === 'fulfilled') {
        const snapshotPayload = parsePayloadData<TradingSnapshotPayload>(snapshotResult.value);
        setThsInfo(snapshotPayload?.channel_info ?? null);
        const snapshotOrders = Array.isArray(snapshotPayload?.orders) ? snapshotPayload.orders : [];
        setFills(buildFillsFromSnapshotOrders(snapshotOrders));
      } else {
        setFills([]);
      }
    } catch (error) {
      console.warn('[ExecutionMonitor] 数据拉取失败', error);
      setOrders([]);
      setFills([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  const latestFills = useMemo(() => fills.slice(0, 20), [fills]);

  const handleSyncOrders = async () => {
    setSyncingOrders(true);
    setActionMessage('');
    try {
      await tradingApi.syncOrders();
      setActionMessage('订单已完成同步。');
      await fetchData();
    } catch (error) {
      setActionMessage(`同步失败: ${String(error)}`);
    } finally {
      setSyncingOrders(false);
    }
  };

  const handleEmergencyStop = async () => {
    const confirmed = window.confirm('确认触发紧急停机（暂停交易）？');
    if (!confirmed) {
      return;
    }

    setStoppingTrading(true);
    setActionMessage('');
    try {
      await monitorApi.toggleRiskSwitch({ name: 'trading_pause', enabled: true });
      setActionMessage('已触发交易暂停。');
    } catch (error) {
      setActionMessage(`停机失败: ${String(error)}`);
    } finally {
      setStoppingTrading(false);
    }
  };

  const handleSwitchToSimulator = async () => {
    const confirmed = window.confirm('确认切换到 simulation 模拟通道？');
    if (!confirmed) {
      return;
    }

    setSwitchingChannel(true);
    setActionMessage('');
    try {
      const switchPayload = await tradingApi.switchChannel<{ active_channel?: string }>({ channel: 'simulation', reconnect: true });
      const switchResult = parsePayloadData<{ active_channel?: string }>(switchPayload);
      setActionMessage(`通道已切换: ${String(switchResult?.active_channel ?? 'simulation')}`);
      await fetchData();
    } catch (error) {
      setActionMessage(`切换失败: ${String(error)}`);
    } finally {
      setSwitchingChannel(false);
    }
  };

  const handleCancelAllOrders = async () => {
    if (orders.length === 0) {
      setActionMessage('当前无可撤销订单。');
      return;
    }
    const confirmed = window.confirm(`确认撤销当前 ${orders.length} 笔活动订单？`);
    if (!confirmed) {
      return;
    }

    setCancelingOrders(true);
    setActionMessage('');
    try {
      const cancelPayload = await tradingApi.cancelAllOrders<{ cancelled?: number; failed?: number }>({
        reason: 'execution_monitor_ui',
      });
      const cancelResult = parsePayloadData<{ cancelled?: number; failed?: number }>(cancelPayload);
      const cancelled = toNumber(cancelResult?.cancelled, 0);
      const failed = toNumber(cancelResult?.failed, 0);
      setActionMessage(`批量撤单完成: 成功 ${cancelled} 笔，失败 ${failed} 笔。`);
      await fetchData();
    } catch (error) {
      setActionMessage(`批量撤单失败: ${String(error)}`);
    } finally {
      setCancelingOrders(false);
    }
  };

  return (
    <div className="p-6 space-y-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:justify-between lg:items-end">
        <PageTitle title="执行监控" subtitle="实时订单队列、通道状态与成交回报" />
        <div className="flex gap-3 h-10">
          <button
            onClick={() => void handleSyncOrders()}
            disabled={syncingOrders}
            className="flex items-center gap-2 px-4 py-2 bg-bg-card border border-border rounded-sm hover:border-neon-cyan hover:bg-bg-hover transition-all text-sm group disabled:opacity-60"
          >
            <RefreshCw className={cn('h-4 w-4', syncingOrders && 'animate-spin')} />
            <span>同步订单</span>
          </button>
          <button
            onClick={() => void handleSwitchToSimulator()}
            disabled={switchingChannel}
            className="flex items-center gap-2 px-4 py-2 bg-bg-card border border-border rounded-sm text-sm hover:border-neon-cyan hover:bg-bg-hover transition-all disabled:opacity-60"
          >
            {switchingChannel ? <Loader2 className="h-4 w-4 animate-spin" /> : <Cpu className="h-4 w-4" />}
            <span>{switchingChannel ? '切换中...' : '切换到模拟器'}</span>
          </button>
          <button
            onClick={() => void handleEmergencyStop()}
            disabled={stoppingTrading}
            className="flex items-center gap-2 px-4 py-2 bg-down-red/20 border border-down-red/50 rounded-sm hover:bg-down-red/40 transition-all text-sm text-down-red font-bold disabled:opacity-60"
          >
            {stoppingTrading ? <Loader2 className="h-4 w-4 animate-spin" /> : <AlertOctagon className="h-4 w-4" />}
            <span>紧急停机</span>
          </button>
        </div>
      </div>

      {actionMessage && (
        <div className="text-xs px-3 py-2 border border-border rounded bg-bg-card text-info-gray">{actionMessage}</div>
      )}

      {thsInfo && (
        <div className="bg-bg-card border border-border rounded-sm p-4 border-l-4 border-l-neon-cyan/50">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div className="flex flex-col">
              <div className="flex items-center gap-2 mb-1">
                <Cpu className="h-4 w-4 text-neon-cyan" />
                <span className="font-orbitron font-bold text-sm tracking-widest uppercase">实盘下单通道</span>
              </div>
              <p className="text-info-gray/60 text-[10px] font-mono">A 股实盘自动下单通道（ths_auto）</p>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-6 flex-1 max-w-2xl px-4">
              <div className="flex flex-col">
                <span className="text-[9px] text-info-gray/50 uppercase font-mono">通道名称</span>
                <span className="text-xs text-white font-bold">{String(thsInfo.name ?? '--')}</span>
              </div>
              <div className="flex flex-col">
                <span className="text-[9px] text-info-gray/50 uppercase font-mono">HWND</span>
                <span className="text-xs text-neon-cyan font-mono">{String(thsInfo.hwnd ?? '--')}</span>
              </div>
              <div className="flex flex-col">
                <span className="text-[9px] text-info-gray/50 uppercase font-mono">窗口标题</span>
                <span className="text-xs text-white truncate max-w-[150px]" title={String(thsInfo.title ?? '--')}>
                  {String(thsInfo.title ?? '--')}
                </span>
              </div>
              <div className="flex flex-col">
                <span className="text-[9px] text-info-gray/50 uppercase font-mono">连接状态</span>
                <span className={cn('text-xs font-bold', String(thsInfo.status ?? '').includes('NOT') ? 'text-down-red' : 'text-up-green')}>
                  {String(thsInfo.status ?? 'CONNECTED')}
                </span>
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {channels.map((channel) => (
          <div key={channel.id} className="bg-bg-card border border-border rounded-sm p-4 relative group hover:border-neon-cyan/30 transition-colors">
            <div className="flex justify-between items-start mb-4">
              <div className="flex items-center gap-2">
                {channel.status === 'online' ? <Wifi className="h-4 w-4 text-up-green" /> : <WifiOff className="h-4 w-4 text-down-red" />}
                <span className="font-orbitron font-bold text-lg tracking-wider">{channel.name}</span>
              </div>
              <div
                className={cn(
                  'px-2 py-0.5 rounded-full text-[10px] uppercase font-bold border',
                  channel.status === 'online'
                    ? 'bg-up-green/10 text-up-green border-up-green/20'
                    : 'bg-warn-gold/10 text-warn-gold border-warn-gold/20',
                )}
              >
                {channel.status}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4 text-xs font-mono">
              <div className="flex flex-col">
                <span className="text-info-gray/50 uppercase">延迟</span>
                <span className={cn('text-lg', channel.latency > 50 ? 'text-warn-gold' : 'text-up-green')}>
                  {channel.latency} <span className="text-[10px] text-info-gray/50">ms</span>
                </span>
              </div>
              <div className="flex flex-col">
                <span className="text-info-gray/50 uppercase">吞吐</span>
                <span className="text-lg text-white">
                  {channel.throughput} <span className="text-[10px] text-info-gray/50">cmd/s</span>
                </span>
              </div>
              <div className="flex flex-col col-span-2">
                <span className="text-info-gray/50 uppercase">最近同步</span>
                <span className="text-white">{channel.lastSync}</span>
              </div>
            </div>

            <div className="absolute top-0 right-0 p-1 opacity-0 group-hover:opacity-100 transition-opacity">
              <ExternalLink className="h-3 w-3 text-info-gray cursor-pointer hover:text-white" />
            </div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 h-[500px]">
        <div className="lg:col-span-2 flex flex-col bg-bg-card border border-border rounded-sm overflow-hidden">
          <div className="flex justify-between items-center px-4 py-3 border-b border-border bg-bg-card/50">
            <div className="flex items-center gap-2">
              <Activity className="h-4 w-4 text-neon-cyan" />
              <span className="font-orbitron text-sm font-bold tracking-widest uppercase">活动订单队列</span>
            </div>
            <button
              onClick={() => void handleCancelAllOrders()}
              disabled={cancelingOrders || orders.length === 0}
              className="flex items-center gap-1.5 px-3 py-1 bg-down-red/10 border border-down-red/30 rounded-sm text-[10px] font-bold text-down-red uppercase disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {cancelingOrders ? <Loader2 className="h-3 w-3 animate-spin" /> : <Ban className="h-3 w-3" />}
              {cancelingOrders ? '撤单中...' : '全部撤单'}
            </button>
          </div>

          <div className="flex-1 overflow-auto custom-scrollbar">
            <table className="w-full text-left text-xs">
              <thead className="sticky top-0 bg-bg-card border-b border-border z-10">
                <tr className="text-info-gray uppercase font-mono tracking-tighter">
                  <th className="px-4 py-3">订单 ID</th>
                  <th className="px-4 py-3">证券</th>
                  <th className="px-4 py-3">方向</th>
                  <th className="px-4 py-3 text-right">价格</th>
                  <th className="px-4 py-3 text-right">数量</th>
                  <th className="px-4 py-3">状态</th>
                  <th className="px-4 py-3">持有时间</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-border/30">
                {orders.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="px-4 py-8 text-center text-info-gray/60">
                      {loading ? '加载中...' : '当前无活动订单'}
                    </td>
                  </tr>
                ) : (
                  orders.map((order) => (
                    <tr key={order.id} className="hover:bg-bg-hover transition-colors group">
                      <td className="px-4 py-3 font-mono text-info-gray">{order.id}</td>
                      <td className="px-4 py-3">
                        <div className="flex flex-col">
                          <span className="font-bold text-white">{order.name}</span>
                          <span className="text-[10px] text-info-gray/60">{order.symbol}</span>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <div className={cn('flex items-center gap-1 font-bold', order.side === 'BUY' ? 'text-up-green' : 'text-down-red')}>
                          {order.side === 'BUY' ? <ArrowUpCircle className="h-3 w-3" /> : <ArrowDownCircle className="h-3 w-3" />}
                          {order.side}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-right font-mono">{order.price.toFixed(2)}</td>
                      <td className="px-4 py-3 text-right font-mono">{order.qty}</td>
                      <td className="px-4 py-3">
                        <span
                          className={cn(
                            'px-2 py-0.5 rounded-sm text-[10px] font-bold border',
                            STATUS_MAP[order.status]?.color || 'text-info-gray/70 bg-info-gray/10 border-info-gray/20',
                          )}
                        >
                          {STATUS_MAP[order.status]?.label || order.status}
                        </span>
                      </td>
                      <td className="px-4 py-3 font-mono text-info-gray/60">{order.duration}</td>
                      <td className="px-4 py-3 text-right">
                        <button className="opacity-0 group-hover:opacity-100 p-1 hover:text-down-red transition-all" title="刷新订单状态">
                          <RotateCw className="h-3.5 w-3.5" />
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="flex flex-col bg-bg-card border border-border rounded-sm overflow-hidden">
          <div className="px-4 py-3 border-b border-border bg-bg-card/50 flex items-center gap-2">
            <Clock className="h-4 w-4 text-neon-cyan" />
            <span className="font-orbitron text-sm font-bold tracking-widest uppercase">成交回报流</span>
          </div>

          <div className="flex-1 overflow-auto p-4 space-y-3 custom-scrollbar">
            {loading && latestFills.length === 0 ? (
              <div className="flex items-center justify-center h-full text-info-gray/40">
                <Loader2 className="h-6 w-6 animate-spin mr-2" />
                <span>加载中...</span>
              </div>
            ) : latestFills.length === 0 ? (
              <div className="text-center text-info-gray/60 py-10">暂无可展示成交回报</div>
            ) : (
              latestFills.map((fill) => (
                <div key={fill.id} className="bg-bg-primary/50 border border-border/50 rounded p-3 flex flex-col gap-2 relative overflow-hidden group">
                  <div
                    className={cn(
                      'absolute left-0 top-0 bottom-0 w-1',
                      fill.side === 'BUY'
                        ? 'bg-up-green shadow-[0_0_8px_rgba(0,255,157,0.5)]'
                        : 'bg-down-red shadow-[0_0_8px_rgba(255,0,85,0.5)]',
                    )}
                  />

                  <div className="flex justify-between items-start">
                    <div className="flex flex-col">
                      <span className="text-white font-bold">{fill.symbol}</span>
                      <span className={cn('text-[10px] font-bold uppercase', fill.side === 'BUY' ? 'text-up-green' : 'text-down-red')}>
                        {fill.status}
                      </span>
                    </div>
                    <span className="text-[10px] text-info-gray/50 font-mono">{fill.time}</span>
                  </div>

                  <div className="grid grid-cols-2 gap-2 text-[11px] font-mono">
                    <div className="flex justify-between border-r border-border/50 pr-2">
                      <span className="text-info-gray/50 uppercase">均价</span>
                      <span className="text-white font-bold">{fill.avgPrice.toFixed(2)}</span>
                    </div>
                    <div className="flex justify-between pl-2">
                      <span className="text-info-gray/50 uppercase">成交数量</span>
                      <span className="text-white font-bold">{fill.qty}</span>
                    </div>
                  </div>

                  <div className="absolute inset-0 bg-gradient-to-t from-transparent via-white/5 to-transparent h-4 -top-full group-hover:top-full transition-all duration-1000" />
                </div>
              ))
            )}
          </div>

          <div className="p-3 bg-bg-primary/30 border-t border-border flex justify-between items-center text-[10px] text-info-gray/40">
            <span>实时数据流已激活</span>
            <div className="flex items-center gap-1.5">
              <div className="h-1.5 w-1.5 rounded-full bg-up-green animate-ping" />
              <span>已同步</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ExecutionMonitor;
