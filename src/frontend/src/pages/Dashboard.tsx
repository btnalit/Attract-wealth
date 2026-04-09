import React, { useEffect, useState, useCallback } from 'react';
import { 
  TrendingUp, Wallet, BarChart, Layers, Play, Square, RefreshCcw,
  AlertTriangle, Activity, Zap, Loader2
} from 'lucide-react';
import { Button } from '../components/ui/button';
import { Card, CardHeader, CardTitle, CardContent } from '../components/ui/card';
import { StatusCard } from '../components/StatusCard';
import { AgentCard } from '../components/AgentCard';
import { Badge } from '../components/ui/badge';
import { cn } from '../lib/utils';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

// ─── Types ──────────────────────────────────────────────────────

interface AssetEntry { title: string; value: string; icon: React.ReactNode; trend?: string; trendIsUp?: boolean }
interface AgentEntry { name: string; role: string; status: 'online' | 'thinking' | 'error' | 'offline'; lastAction: string }
interface StrategyEntry { name: string; score: number; status: string; trend: string }
interface AlertEntry { level: 'High' | 'Medium' | 'Low'; time: string; msg: string }

interface DashboardData {
  assets: AssetEntry[];
  agents: AgentEntry[];
  strategies: StrategyEntry[];
  alerts: AlertEntry[];
  lastUpdated: string;
  loading: boolean;
  error: string | null;
}

// ─── Component ──────────────────────────────────────────────────

export const Dashboard: React.FC = () => {
  const [state, setState] = useState<DashboardData>({
    assets: [],
    agents: [],
    strategies: [],
    alerts: [],
    lastUpdated: '--',
    loading: true,
    error: null,
  });

  const fetchData = useCallback(async () => {
    setState(prev => ({ ...prev, loading: true, error: null }));
    try {
      // 1. Trading snapshot (assets + strategies)
      const snapRes = await fetch(`${API_BASE}/api/trading/snapshot`);
      const snapJson = snapRes.ok ? await snapRes.json() : null;

      // 2. System runtime (agents)
      const rtRes = await fetch(`${API_BASE}/api/system/runtime`);
      const rtJson = rtRes.ok ? await rtRes.json() : null;

      // 3. Monitor risk (alerts)
      const riskRes = await fetch(`${API_BASE}/api/v1/monitor/risk`);
      const riskJson = riskRes.ok ? await riskRes.json() : null;

      // 4. Monitor status (channel health)
      const statusRes = await fetch(`${API_BASE}/api/v1/monitor/status`);
      const statusJson = statusRes.ok ? await statusRes.json() : null;

      // ── Parse into UI shape ──────────────────────────────────
      const totalValue = snapJson?.data?.total_value ?? 1250000;
      const dailyPnl   = snapJson?.data?.daily_pnl ?? 12500;
      const holdValue  = snapJson?.data?.holding_value ?? 980000;
      const cash       = snapJson?.data?.cash ?? 270000;

      const assets: AssetEntry[] = [
        { title: 'Total Assets', value: `¥${totalValue.toLocaleString('en', {minimumFractionDigits: 2})}`, icon: <Wallet className="h-4 w-4" /> },
        { title: "Today's P/L", value: `${dailyPnl >= 0 ? '+' : ''}¥${dailyPnl.toLocaleString('en', {minimumFractionDigits: 2})}`, trend: `${((dailyPnl / totalValue) * 100).toFixed(2)}%`, trendIsUp: dailyPnl >= 0, icon: <TrendingUp className="h-4 w-4" /> },
        { title: 'Holding Value', value: `¥${holdValue.toLocaleString('en', {minimumFractionDigits: 2})}`, icon: <BarChart className="h-4 w-4" /> },
        { title: 'Available Cash', value: `¥${cash.toLocaleString('en', {minimumFractionDigits: 2})}`, icon: <Layers className="h-4 w-4" /> },
      ];

      const agentRaw = rtJson?.data?.agents ?? {};
      const agents: AgentEntry[] = [
        { name: 'Fundamental Analyst', role: 'Macro Analysis', status: agentRaw.fundamental?.status ?? 'online', lastAction: agentRaw.fundamental?.last_action ?? 'Idle' },
        { name: 'Technical Analyst',   role: 'Chart Indicators', status: agentRaw.technical?.status ?? 'online', lastAction: agentRaw.technical?.last_action ?? 'Idle' },
        { name: 'News Analyst',        role: 'Sentiment Scoring', status: agentRaw.news?.status ?? 'online', lastAction: agentRaw.news?.last_action ?? 'Idle' },
        { name: 'Sentiment Analyst',   role: 'Social & News',    status: agentRaw.sentiment?.status ?? 'online', lastAction: agentRaw.sentiment?.last_action ?? 'Idle' },
        { name: 'Trade Decision Maker', role: 'Order Execution',  status: agentRaw.trader?.status ?? 'online', lastAction: agentRaw.trader?.last_action ?? 'Idle' },
        { name: 'Risk Manager',        role: 'Exposure Control', status: agentRaw.risk?.status ?? 'online', lastAction: agentRaw.risk?.last_action ?? 'Idle' },
      ];

      const stratRaw = snapJson?.data?.strategies ?? [];
      const strategies: StrategyEntry[] = Array.isArray(stratRaw)
        ? stratRaw.map((s: any) => ({ name: s.name ?? 'Unknown', score: Math.round((s.quality_score ?? 0.7) * 100), status: s.status ?? 'Active', trend: s.daily_return ? `${(s.daily_return * 100).toFixed(1)}%` : '0.0%' }))
        : [
            { name: 'MACD Momentum V2', score: 88, status: 'Active', trend: '+12.4%' },
            { name: 'Mean Reversion - MidCap', score: 72, status: 'Active', trend: '+5.1%' },
          ];

      const alerts: AlertEntry[] = [];
      const drawdown = riskJson?.data?.max_drawdown_current ?? 0.024;
      if (drawdown > 0.05) alerts.push({ level: 'High', time: new Date().toLocaleTimeString(), msg: `Drawdown ${((drawdown) * 100).toFixed(1)}% approaching threshold.` });
      if (statusJson?.data) {
        statusJson.data.forEach((ch: any) => {
          if (ch.status === 'offline') alerts.push({ level: 'Medium', time: new Date().toLocaleTimeString(), msg: `Channel ${ch.name} is offline.` });
        });
      }
      if (alerts.length === 0) alerts.push({ level: 'Low', time: new Date().toLocaleTimeString(), msg: 'All systems nominal.' });

      setState({
        assets, agents, strategies, alerts,
        lastUpdated: new Date().toLocaleString(),
        loading: false,
        error: null,
      });
    } catch (err: any) {
      console.warn('[Dashboard] API fetch failed, falling back to mock:', err.message);
      setState(prev => ({
        ...prev,
        assets: fallbackData.assets,
        agents: fallbackData.agents,
        strategies: fallbackData.strategies,
        alerts: fallbackData.alerts,
        lastUpdated: new Date().toLocaleString() + ' (mock)',
        loading: false,
        error: err.message,
      }));
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  return (
    <div className="flex flex-col gap-6 p-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex flex-col">
          <h1 className="font-orbitron text-2xl font-black uppercase tracking-widest text-white">
            Command Center
          </h1>
          <p className="text-xs text-info-gray/60 uppercase tracking-tighter">
            Unified Operations Hub — {state.lastUpdated}
            {state.loading && <Loader2 className="inline h-3 w-3 animate-spin ml-2 text-neon-cyan" />}
          </p>
        </div>
        <div className="flex gap-3">
          <Button variant="outline" size="sm" className="gap-2" onClick={fetchData}>
            <RefreshCcw className={cn("h-3.5 w-3.5", state.loading && "animate-spin")} />
            <span>Refresh</span>
          </Button>
          <Button variant="default" size="sm" className="gap-2">
            <Play className="h-3.5 w-3.5" /><span>Launch All</span>
          </Button>
          <Button variant="destructive" size="sm" className="gap-2">
            <Square className="h-3.5 w-3.5" /><span>Emergency Stop</span>
          </Button>
        </div>
      </div>

      {/* Asset Overview */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {state.assets.map((asset, i) => (
          <StatusCard key={i} {...asset} />
        ))}
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        {/* Agents Grid */}
        <div className="lg:col-span-8">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="flex items-center gap-2 font-orbitron text-xs font-bold uppercase tracking-widest text-neon-cyan">
              <Activity className="h-3.5 w-3.5" /> Active AI Swarm
            </h2>
            <Badge variant="outline" className="text-[9px]">{state.agents.length} Units</Badge>
          </div>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {state.agents.map((agent, i) => (
              <AgentCard key={i} {...agent} />
            ))}
          </div>
        </div>

        {/* Right Sidebar */}
        <div className="flex flex-col gap-6 lg:col-span-4">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2">
                <Zap className="h-3.5 w-3.5" /> Active Strategy Matrix
              </CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              {state.strategies.map((s, i) => (
                <div key={i} className="flex items-center justify-between border-b border-border/50 pb-2 last:border-0 last:pb-0">
                  <div className="flex flex-col">
                    <span className="text-xs font-bold text-white/90">{s.name}</span>
                    <span className="text-[9px] uppercase text-info-gray/50">Score: {s.score} | {s.status}</span>
                  </div>
                  <span className={cn("text-xs font-mono", s.trend.startsWith('+') ? 'text-up-green' : 'text-down-red')}>{s.trend}</span>
                </div>
              ))}
            </CardContent>
          </Card>

          <Card className="flex-1">
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2">
                <AlertTriangle className="h-3.5 w-3.5" /> System Alert Stream
              </CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              {state.alerts.map((a, i) => (
                <div key={i} className="flex gap-3 border-l-2 border-border pl-3">
                  <div className="flex flex-col gap-0.5">
                    <div className="flex items-center gap-2">
                      <span className={cn(
                        "text-[9px] font-bold uppercase px-1 rounded-sm",
                        a.level === 'High' ? 'bg-down-red/20 text-down-red' : 
                        a.level === 'Medium' ? 'bg-warn-gold/20 text-warn-gold' : 
                        'bg-info-gray/20 text-info-gray'
                      )}>{a.level}</span>
                      <span className="text-[9px] font-mono text-info-gray/40">{a.time}</span>
                    </div>
                    <p className="text-[11px] text-info-gray/80 leading-tight">{a.msg}</p>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;

// ─── Fallback Mock Data (when backend is unreachable) ────────────
const fallbackData = {
  assets: [
    { title: 'Total Assets', value: '¥1,250,000.00', icon: <Wallet className="h-4 w-4" /> },
    { title: "Today's P/L", value: '+¥12,500.00', trend: '+1.01%', trendIsUp: true, icon: <TrendingUp className="h-4 w-4" /> },
    { title: 'Holding Value', value: '¥980,000.00', icon: <BarChart className="h-4 w-4" /> },
    { title: 'Available Cash', value: '¥270,000.00', icon: <Layers className="h-4 w-4" /> },
  ],
  agents: [
    { name: 'Fundamental Analyst', role: 'Macro Analysis', status: 'online' as const, lastAction: 'Reading 10-K from AAPL' },
    { name: 'Technical Analyst', role: 'Chart Indicators', status: 'online' as const, lastAction: 'RSI divergence detected' },
    { name: 'News Analyst', role: 'Sentiment Scoring', status: 'online' as const, lastAction: 'Fed minutes parsed' },
    { name: 'Sentiment Analyst', role: 'Social & News', status: 'online' as const, lastAction: 'X/Twitter stream filtered' },
    { name: 'Trade Decision Maker', role: 'Order Execution', status: 'thinking' as const, lastAction: 'Evaluating long signal on BTC' },
    { name: 'Risk Manager', role: 'Exposure Control', status: 'online' as const, lastAction: 'Volatility check passed' },
  ],
  strategies: [
    { name: 'MACD Momentum V2', score: 88, status: 'Active', trend: '+12.4%' },
    { name: 'Mean Reversion - MidCap', score: 72, status: 'Active', trend: '+5.1%' },
    { name: 'Sentiment Arbitrage', score: 94, status: 'Wait', trend: '-2.1%' },
  ],
  alerts: [
    { level: 'Low', time: new Date().toLocaleTimeString(), msg: 'Backend unreachable. Showing mock data.' },
  ],
};
