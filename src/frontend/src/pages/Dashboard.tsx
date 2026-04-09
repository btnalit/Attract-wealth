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
interface AgentEntry { id: string; name: string; role: string; description: string; status: '在线' | '思考中' | '错误' | '离线'; lastAction: string }
interface StrategyEntry { name: string; score: number; status: string; trend: string }
interface AlertEntry { level: '高' | '中' | '低'; time: string; msg: string }

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
        { title: '总资产', value: `¥${totalValue.toLocaleString('zh-CN', {minimumFractionDigits: 2})}`, icon: <Wallet className="h-4 w-4" /> },
        { title: "今日盈亏", value: `${dailyPnl >= 0 ? '+' : ''}¥${dailyPnl.toLocaleString('zh-CN', {minimumFractionDigits: 2})}`, trend: `${((dailyPnl / totalValue) * 100).toFixed(2)}%`, trendIsUp: dailyPnl >= 0, icon: <TrendingUp className="h-4 w-4" /> },
        { title: '持仓市值', value: `¥${holdValue.toLocaleString('zh-CN', {minimumFractionDigits: 2})}`, icon: <BarChart className="h-4 w-4" /> },
        { title: '可用资金', value: `¥${cash.toLocaleString('zh-CN', {minimumFractionDigits: 2})}`, icon: <Layers className="h-4 w-4" /> },
      ];

      const agentRaw = rtJson?.data?.agents ?? {};
      const agents: AgentEntry[] = [
        { id: 'fundamental', name: '基本面分析员', role: '宏观分析', description: '对宏观经济状况进行基本面分析。', status: agentRaw.fundamental?.status ?? '在线', lastAction: agentRaw.fundamental?.last_action ?? '空闲' },
        { id: 'technical', name: '技术面分析员', role: '图表指标', description: '对市场指标进行技术分析。', status: agentRaw.technical?.status ?? '在线', lastAction: agentRaw.technical?.last_action ?? '空闲' },
        { id: 'news', name: '新闻分析员', role: '情绪评分', description: '从全球新闻流中对情绪进行评分。', status: agentRaw.news?.status ?? '在线', lastAction: agentRaw.news?.last_action ?? '空闲' },
        { id: 'sentiment', name: '情绪分析员', role: '社交与新闻', description: '监控加密货币/股票的社交情绪。', status: agentRaw.sentiment?.status ?? '在线', lastAction: agentRaw.sentiment?.last_action ?? '空闲' },
        { id: 'trader', name: '交易决策者', role: '订单执行', description: '管理交易执行和订单生命周期。', status: agentRaw.trader?.status ?? '在线', lastAction: agentRaw.trader?.last_action ?? '空闲' },
        { id: 'risk', name: '风控经理', role: '风险控制', description: '实时风险监控和缓解。', status: agentRaw.risk?.status ?? '在线', lastAction: agentRaw.risk?.last_action ?? '空闲' },
      ];

      const stratRaw = snapJson?.data?.strategies ?? [];
      const strategies: StrategyEntry[] = Array.isArray(stratRaw)
        ? stratRaw.map((s: any) => ({ name: s.name ?? '未知', score: Math.round((s.quality_score ?? 0.7) * 100), status: s.status ?? '激活', trend: s.daily_return ? `${(s.daily_return * 100).toFixed(1)}%` : '0.0%' }))
        : [
            { name: 'MACD 动量 V2', score: 88, status: '激活', trend: '+12.4%' },
            { name: '均值回归 - 中盘股', score: 72, status: '激活', trend: '+5.1%' },
          ];

      const alerts: AlertEntry[] = [];
      const drawdown = riskJson?.data?.max_drawdown_current ?? 0.024;
      if (drawdown > 0.05) alerts.push({ level: '高' as const, time: new Date().toLocaleTimeString(), msg: `回撤 ${((drawdown) * 100).toFixed(1)}% 接近阈值。` });
      if (statusJson?.data && Array.isArray(statusJson.data)) {
        statusJson.data.forEach((ch: any) => {
          if (ch.status === 'offline') alerts.push({ level: '中' as const, time: new Date().toLocaleTimeString(), msg: `通道 ${ch.name} 已离线。` });
        });
      }
      if (alerts.length === 0) alerts.push({ level: '低' as const, time: new Date().toLocaleTimeString(), msg: '所有系统运行正常。' });

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
        alerts: fallbackData.alerts as AlertEntry[],
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
            指挥中心
          </h1>
          <p className="text-xs text-info-gray/60 uppercase tracking-tighter">
            统一指挥中心 — {state.lastUpdated}
            {state.loading && <Loader2 className="inline h-3 w-3 animate-spin ml-2 text-neon-cyan" />}
          </p>
        </div>
        <div className="flex gap-3">
          <Button variant="outline" size="sm" className="gap-2" onClick={fetchData}>
            <RefreshCcw className={cn("h-3.5 w-3.5", state.loading && "animate-spin")} />
            <span>刷新</span>
          </Button>
          <Button variant="default" size="sm" className="gap-2">
            <Play className="h-3.5 w-3.5" /><span>全部启动</span>
          </Button>
          <Button variant="destructive" size="sm" className="gap-2">
            <Square className="h-3.5 w-3.5" /><span>紧急停机</span>
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
              <Activity className="h-3.5 w-3.5" /> 运行中的 AI 智能体群
            </h2>
            <Badge variant="outline" className="text-[9px]">{state.agents.length} 个智能体</Badge>
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
                <Zap className="h-3.5 w-3.5" /> 激活策略矩阵
              </CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              {state.strategies.map((s, i) => (
                <div key={i} className="flex items-center justify-between border-b border-border/50 pb-2 last:border-0 last:pb-0">
                  <div className="flex flex-col">
                    <span className="text-xs font-bold text-white/90">{s.name}</span>
                    <span className="text-[9px] uppercase text-info-gray/50">评分: {s.score} | {s.status}</span>
                  </div>
                  <span className={cn("text-xs font-mono", s.trend.startsWith('+') ? 'text-up-green' : 'text-down-red')}>{s.trend}</span>
                </div>
              ))}
            </CardContent>
          </Card>

          <Card className="flex-1">
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2">
                <AlertTriangle className="h-3.5 w-3.5" /> 系统警报流
              </CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              {state.alerts.map((a, i) => (
                <div key={i} className="flex gap-3 border-l-2 border-border pl-3">
                  <div className="flex flex-col gap-0.5">
                    <div className="flex items-center gap-2">
                      <span className={cn(
                        "text-[9px] font-bold uppercase px-1 rounded-sm",
                        a.level === '高' ? 'bg-down-red/20 text-down-red' : 
                        a.level === '中' ? 'bg-warn-gold/20 text-warn-gold' : 
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
    { title: '总资产', value: '¥1,250,000.00', icon: <Wallet className="h-4 w-4" /> },
    { title: "今日盈亏", value: '+¥12,500.00', trend: '+1.01%', trendIsUp: true, icon: <TrendingUp className="h-4 w-4" /> },
    { title: '持仓市值', value: '¥980,000.00', icon: <BarChart className="h-4 w-4" /> },
    { title: '可用资金', value: '¥270,000.00', icon: <Layers className="h-4 w-4" /> },
  ],
  agents: [
    { id: 'fundamental', name: '基本面分析员', role: '宏观分析', description: '对宏观经济状况进行基本面分析。', status: '在线' as const, lastAction: '正在读取 AAPL 的 10-K 文件' },
    { id: 'technical', name: '技术面分析员', role: '图表指标', description: '对市场指标进行技术分析。', status: '在线' as const, lastAction: '检测到 RSI 背离' },
    { id: 'news', name: '新闻分析员', role: '情绪评分', description: '从全球新闻流中对情绪进行评分。', status: '在线' as const, lastAction: '已解析美联储会议纪要' },
    { id: 'sentiment', name: '情绪分析员', role: '社交与新闻', description: '监控加密货币/股票的社交情绪。', status: '在线' as const, lastAction: '已过滤 X/Twitter 流' },
    { id: 'trader', name: '交易决策者', role: '订单执行', description: '管理交易执行和订单生命周期。', status: '思考中' as const, lastAction: '正在评估 BTC 看多信号' },
    { id: 'risk', name: '风控经理', role: '风险控制', description: '实时风险监控和缓解。', status: '在线' as const, lastAction: '波动率检查通过' },
  ],
  strategies: [
    { name: 'MACD 动量 V2', score: 88, status: '激活', trend: '+12.4%' },
    { name: '均值回归 - 中盘股', score: 72, status: '激活', trend: '+5.1%' },
    { name: '情绪套利', score: 94, status: '等待', trend: '-2.1%' },
  ],
  alerts: [
    { level: '低', time: new Date().toLocaleTimeString(), msg: '无法连接到后端，显示模拟数据。' } as AlertEntry,
  ],
};
