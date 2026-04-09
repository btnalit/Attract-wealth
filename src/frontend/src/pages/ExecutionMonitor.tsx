import React, { useState, useEffect, useCallback } from 'react';
import { 
  Activity, Wifi, WifiOff, ArrowUpCircle, ArrowDownCircle, Ban, 
  RotateCw, AlertOctagon, Cpu, RefreshCw, Clock, ExternalLink, Loader2
} from 'lucide-react';
import { cn } from '../lib/utils';
import { PageTitle } from '../components/PageTitle';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

// ─── Types ──────────────────────────────────────────────
interface Channel { id: string; name: string; status: string; latency: number; throughput: number; lastSync: string; color: string }
interface Order { id: string; symbol: string; name: string; side: string; price: number; qty: number; status: string; duration: string }
interface Fill { time: string; symbol: string; side: string; avgPrice: number; qty: number }

const STATUS_MAP: Record<string, { label: string; color: string }> = {
  'PENDING': { label: '待报', color: 'text-info-gray/60 bg-info-gray/10 border-info-gray/20' },
  'SUBMITTED': { label: '已报', color: 'text-neon-cyan bg-neon-cyan/10 border-neon-cyan/20' },
  'PARTIAL': { label: '部成', color: 'text-warn-gold bg-warn-gold/10 border-warn-gold/20' },
  'FILLED': { label: '已成', color: 'text-up-green bg-up-green/10 border-up-green/20' },
  'CANCELED': { label: '已撤', color: 'text-down-red bg-down-red/10 border-down-red/20' },
};

// ─── Mock fallback ──────────────────────────────────────
const MOCK_CHANNELS: Channel[] = [
  { id: 'ths_ipc', name: 'THS IPC', status: 'online', latency: 12, throughput: 154, lastSync: '10:45:12', color: 'text-neon-cyan' },
  { id: 'simulator', name: 'Simulator', status: 'online', latency: 2, throughput: 890, lastSync: '10:45:12', color: 'text-up-green' },
  { id: 'mini_qmt', name: 'miniQMT', status: 'paused', latency: 0, throughput: 0, lastSync: '09:30:00', color: 'text-warn-gold' },
];
const MOCK_ORDERS: Order[] = [
  { id: 'ORD_9281', symbol: '600519', name: '贵州茅台', side: 'BUY', price: 1745.2, qty: 100, status: 'FILLED', duration: '0.4s' },
  { id: 'ORD_9282', symbol: '000001', name: '平安银行', side: 'SELL', price: 12.45, qty: 5000, status: 'PARTIAL', duration: '1.2s' },
];
const MOCK_FILLS: Fill[] = [
  { time: '10:45:08', symbol: '600519', side: 'BUY', avgPrice: 1745.2, qty: 100 },
];

// ─── Component ──────────────────────────────────────────
export const ExecutionMonitor: React.FC = () => {
  const [channels, setChannels] = useState<Channel[]>(MOCK_CHANNELS);
  const [orders, setOrders] = useState<Order[]>(MOCK_ORDERS);
  const [fills, setFills] = useState<Fill[]>(MOCK_FILLS);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [statusRes, ordersRes] = await Promise.all([
        fetch(`${API_BASE}/api/v1/monitor/status`),
        fetch(`${API_BASE}/api/trading/orders/active?limit=50`),
      ]);

      if (statusRes.ok) {
        const json = await statusRes.json();
        const raw = json.data ?? json;
        setChannels(Array.isArray(raw) ? raw.map((c: any) => ({
          id: c.name?.toLowerCase().replace(/\s+/g, '_') ?? c.name,
          name: c.name,
          status: c.status,
          latency: Math.round(c.latency_ms),
          throughput: c.throughput,
          lastSync: new Date(c.last_sync * 1000).toLocaleTimeString(),
          color: c.status === 'online' ? 'text-up-green' : 'text-warn-gold',
        })) : MOCK_CHANNELS);
      }

      if (ordersRes.ok) {
        const json = await ordersRes.json();
        const raw = json.data ?? json;
        setOrders(Array.isArray(raw) ? raw.map((o: any) => ({
          id: o.id ?? `ORD_${Math.floor(Math.random() * 10000)}`,
          symbol: o.symbol ?? o.ticker ?? 'N/A',
          name: o.symbol ?? o.ticker ?? 'N/A',
          side: (o.side ?? 'BUY').toUpperCase(),
          price: o.price ?? 0,
          qty: o.quantity ?? o.qty ?? 0,
          status: (o.status ?? 'PENDING').toUpperCase(),
          duration: o.holding_time ? `${(o.holding_time / 1000).toFixed(1)}s` : '0.0s',
        })) : MOCK_ORDERS);
      }
    } catch (err) {
      console.warn('[ExecutionMonitor] API fetch failed, using mock:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  return (
    <div className="p-6 space-y-6">
      <div className="flex justify-between items-end">
        <PageTitle 
          title="EXECUTION MONITOR" 
          subtitle="Real-time order management & channel synchronization" 
        />
        <div className="flex gap-3 h-10">
          <button className="flex items-center gap-2 px-4 py-2 bg-bg-card border border-border rounded-sm hover:border-neon-cyan hover:bg-bg-hover transition-all text-sm group">
            <RefreshCw className="h-4 w-4 group-hover:rotate-180 transition-transform duration-500" />
            <span>SYNC PORTFOLIO</span>
          </button>
          <button className="flex items-center gap-2 px-4 py-2 bg-bg-card border border-border rounded-sm hover:border-up-green hover:bg-bg-hover transition-all text-sm">
            <Cpu className="h-4 w-4" />
            <span>TO SIMULATOR</span>
          </button>
          <button className="flex items-center gap-2 px-4 py-2 bg-down-red/20 border border-down-red/50 rounded-sm hover:bg-down-red/40 transition-all text-sm text-down-red font-bold">
            <AlertOctagon className="h-4 w-4 animate-pulse" />
            <span>EMERGENCY HALT</span>
          </button>
        </div>
      </div>

      {/* Channel Status Grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {channels.map(channel => (
          <div key={channel.id} className="bg-bg-card border border-border rounded-sm p-4 relative group hover:border-neon-cyan/30 transition-colors">
            <div className="flex justify-between items-start mb-4">
              <div className="flex items-center gap-2">
                {channel.status === 'online' ? (
                  <Wifi className="h-4 w-4 text-up-green" />
                ) : (
                  <WifiOff className="h-4 w-4 text-down-red" />
                )}
                <span className="font-orbitron font-bold text-lg tracking-wider">{channel.name}</span>
              </div>
              <div className={cn(
                "px-2 py-0.5 rounded-full text-[10px] uppercase font-bold border",
                channel.status === 'online' ? "bg-up-green/10 text-up-green border-up-green/20" : "bg-warn-gold/10 text-warn-gold border-warn-gold/20"
              )}>
                {channel.status}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4 text-xs font-mono">
              <div className="flex flex-col">
                <span className="text-info-gray/50 uppercase">Latency</span>
                <span className={cn("text-lg", channel.latency > 50 ? "text-warn-gold" : "text-up-green")}>
                  {channel.latency} <span className="text-[10px] text-info-gray/50">ms</span>
                </span>
              </div>
              <div className="flex flex-col">
                <span className="text-info-gray/50 uppercase">Throughput</span>
                <span className="text-lg text-white">
                  {channel.throughput} <span className="text-[10px] text-info-gray/50">cmd/s</span>
                </span>
              </div>
              <div className="flex flex-col">
                <span className="text-info-gray/50 uppercase">Last Sync</span>
                <span className="text-white">{channel.lastSync}</span>
              </div>
              <div className="flex flex-col">
                <span className="text-info-gray/50 uppercase">Load Level</span>
                <div className="flex gap-0.5 mt-1.5 h-1.5 items-end">
                  {[...Array(10)].map((_, i) => (
                    <div 
                      key={i} 
                      className={cn(
                        "w-1 rounded-t-sm", 
                        i < 4 ? "bg-up-green h-full" : 
                        i < 7 ? "bg-warn-gold h-2/3 opacity-30" : 
                        "bg-down-red h-1/3 opacity-10"
                      )}
                    />
                  ))}
                </div>
              </div>
            </div>
            
            <div className="absolute top-0 right-0 p-1 opacity-0 group-hover:opacity-100 transition-opacity">
              <ExternalLink className="h-3 w-3 text-info-gray cursor-pointer hover:text-white" />
            </div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 h-[500px]">
        {/* Active Order Queue */}
        <div className="lg:col-span-2 flex flex-col bg-bg-card border border-border rounded-sm overflow-hidden">
          <div className="flex justify-between items-center px-4 py-3 border-b border-border bg-bg-card/50">
            <div className="flex items-center gap-2">
              <Activity className="h-4 w-4 text-neon-cyan" />
              <span className="font-orbitron text-sm font-bold tracking-widest uppercase">Active Order Queue</span>
            </div>
            <button className="flex items-center gap-1.5 px-3 py-1 bg-down-red/10 border border-down-red/30 rounded-sm text-[10px] font-bold text-down-red hover:bg-down-red/20 transition-all uppercase">
              <Ban className="h-3 w-3" />
              Cancel All
            </button>
          </div>
          
          <div className="flex-1 overflow-auto custom-scrollbar">
            <table className="w-full text-left text-xs">
              <thead className="sticky top-0 bg-bg-card border-b border-border z-10">
                <tr className="text-info-gray uppercase font-mono tracking-tighter">
                  <th className="px-4 py-3">Order ID</th>
                  <th className="px-4 py-3">Security</th>
                  <th className="px-4 py-3">Side</th>
                  <th className="px-4 py-3 text-right">Price</th>
                  <th className="px-4 py-3 text-right">Qty</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Time</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/30">
                {orders.map(order => (
                  <tr key={order.id} className="hover:bg-bg-hover transition-colors group">
                    <td className="px-4 py-3 font-mono text-info-gray">{order.id}</td>
                    <td className="px-4 py-3">
                      <div className="flex flex-col">
                        <span className="font-bold text-white">{order.name}</span>
                        <span className="text-[10px] text-info-gray/60">{order.symbol}</span>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className={cn(
                        "flex items-center gap-1 font-bold",
                        order.side === 'BUY' ? "text-up-green" : "text-down-red"
                      )}>
                        {order.side === 'BUY' ? <ArrowUpCircle className="h-3 w-3" /> : <ArrowDownCircle className="h-3 w-3" />}
                        {order.side}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-right font-mono">{order.price.toFixed(2)}</td>
                    <td className="px-4 py-3 text-right font-mono">{order.qty}</td>
                    <td className="px-4 py-3">
                      <span className={cn(
                        "px-2 py-0.5 rounded-sm text-[10px] font-bold border",
                        STATUS_MAP[order.status as keyof typeof STATUS_MAP]?.color || ""
                      )}>
                        {STATUS_MAP[order.status as keyof typeof STATUS_MAP]?.label || order.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-mono text-info-gray/60">{order.duration}</td>
                    <td className="px-4 py-3 text-right">
                      <button className="opacity-0 group-hover:opacity-100 p-1 hover:text-down-red transition-all">
                        <RotateCw className="h-3.5 w-3.5" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Execution Fill Stream */}
        <div className="flex flex-col bg-bg-card border border-border rounded-sm overflow-hidden">
          <div className="px-4 py-3 border-b border-border bg-bg-card/50 flex items-center gap-2">
            <Clock className="h-4 w-4 text-neon-cyan" />
            <span className="font-orbitron text-sm font-bold tracking-widest uppercase">Execution Return</span>
          </div>
          
          <div className="flex-1 overflow-auto p-4 space-y-3 custom-scrollbar">
            {loading && fills.length === 0 ? (
              <div className="flex items-center justify-center h-full text-info-gray/40">
                <Loader2 className="h-6 w-6 animate-spin mr-2" />
                <span>Streaming...</span>
              </div>
            ) : fills.map((fill, i) => (
              <div key={i} className="bg-bg-primary/50 border border-border/50 rounded p-3 flex flex-col gap-2 relative overflow-hidden group">
                {/* Neon left border indicator */}
                <div className={cn(
                  "absolute left-0 top-0 bottom-0 w-1",
                  fill.side === 'BUY' ? "bg-up-green shadow-[0_0_8px_rgba(0,255,157,0.5)]" : "bg-down-red shadow-[0_0_8px_rgba(255,0,85,0.5)]"
                )} />
                
                <div className="flex justify-between items-start">
                  <div className="flex flex-col">
                    <span className="text-white font-bold">{fill.symbol}</span>
                    <span className={cn(
                      "text-[10px] font-bold uppercase",
                      fill.side === 'BUY' ? "text-up-green" : "text-down-red"
                    )}>
                      Execution Success
                    </span>
                  </div>
                  <span className="text-[10px] text-info-gray/50 font-mono">{fill.time}</span>
                </div>
                
                <div className="grid grid-cols-2 gap-2 text-[11px] font-mono">
                  <div className="flex justify-between border-r border-border/50 pr-2">
                    <span className="text-info-gray/50 uppercase">AVG Price</span>
                    <span className="text-white font-bold">{fill.avgPrice.toFixed(2)}</span>
                  </div>
                  <div className="flex justify-between pl-2">
                    <span className="text-info-gray/50 uppercase">Filled Qty</span>
                    <span className="text-white font-bold">{fill.qty}</span>
                  </div>
                </div>
                
                {/* Scanline decoration for fill item */}
                <div className="absolute inset-0 bg-gradient-to-t from-transparent via-white/5 to-transparent h-4 -top-full group-hover:top-full transition-all duration-1000" />
              </div>
            ))}
          </div>
          
          <div className="p-3 bg-bg-primary/30 border-t border-border flex justify-between items-center text-[10px] text-info-gray/40">
            <span>REAL-TIME STREAM ACTIVE</span>
            <div className="flex items-center gap-1.5">
              <div className="h-1.5 w-1.5 rounded-full bg-up-green animate-ping" />
              <span>SYNCED</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ExecutionMonitor;
an>
            <div className="flex items-center gap-1.5">
              <div className="h-1.5 w-1.5 rounded-full bg-up-green animate-ping" />
              <span>SYNCED</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ExecutionMonitor;
