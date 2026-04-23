import React, { useCallback, useEffect, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  BarChart,
  Layers,
  Loader2,
  Play,
  RefreshCcw,
  Square,
  TrendingUp,
  Wallet,
  Zap,
} from 'lucide-react';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { StatusCard } from '../components/StatusCard';
import { AgentCard } from '../components/AgentCard';
import { cn } from '../lib/utils';
import {
  monitorApi,
  tradingApi,
  type MonitorRiskPayload,
  type MonitorStatusPayload,
  type TradingPositionPayload,
  type TradingSnapshotPayload,
  type TradingStrategyPayload,
} from '../services/api';

interface AssetEntry {
  title: string;
  value: string;
  icon: React.ReactNode;
  trend?: string;
  trendIsUp?: boolean;
}

interface AgentEntry {
  id: string;
  name: string;
  role: string;
  description: string;
}

interface StrategyEntry {
  name: string;
  score: number;
  status: string;
  trend: string;
}

interface AlertEntry {
  level: '高' | '中' | '低';
  time: string;
  msg: string;
}

interface DashboardData {
  assets: AssetEntry[];
  agents: AgentEntry[];
  strategies: StrategyEntry[];
  alerts: AlertEntry[];
  lastUpdated: string;
  loading: boolean;
  error: string | null;
}

const fallbackData: Omit<DashboardData, 'lastUpdated' | 'loading' | 'error'> = {
  assets: [
    { title: '总资产', value: '¥1,250,000.00', icon: <Wallet className="h-4 w-4" /> },
    { title: '今日盈亏', value: '+¥12,500.00', trend: '+1.01%', trendIsUp: true, icon: <TrendingUp className="h-4 w-4" /> },
    { title: '持仓市值', value: '¥980,000.00', icon: <BarChart className="h-4 w-4" /> },
    { title: '可用资金', value: '¥270,000.00', icon: <Layers className="h-4 w-4" /> },
  ],
  agents: [
    { id: 'fundamental', name: '基本面分析员', role: '宏观分析', description: '对宏观经济与行业估值进行分析。' },
    { id: 'technical', name: '技术面分析员', role: '图表指标', description: '跟踪价格行为、趋势结构和量价关系。' },
    { id: 'news', name: '新闻分析员', role: '事件驱动', description: '解析财经新闻、公告和政策冲击。' },
    { id: 'sentiment', name: '情绪分析员', role: '舆情追踪', description: '监控社交平台与媒体情绪变化。' },
    { id: 'trader', name: '交易决策者', role: '订单执行', description: '将策略建议转换为可执行交易指令。' },
    { id: 'risk', name: '风控经理', role: '风险控制', description: '评估仓位风险、回撤风险与执行约束。' },
  ],
  strategies: [
    { name: 'MACD 动量 V2', score: 88, status: '激活', trend: '+12.4%' },
    { name: '均值回归-中盘股', score: 72, status: '激活', trend: '+5.1%' },
    { name: '情绪套利', score: 94, status: '等待', trend: '-2.1%' },
  ],
  alerts: [
    { level: '低', time: new Date().toLocaleTimeString(), msg: '无法连接后端，当前展示回退数据。' },
  ],
};

const parsePayloadData = <T,>(payload: unknown): T => {
  if (payload && typeof payload === 'object' && 'data' in payload) {
    return (payload as { data: T }).data;
  }
  return payload as T;
};

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
    setState((prev) => ({ ...prev, loading: true, error: null }));
    try {
      const [snapPayload, riskPayload, statusPayload] = await Promise.all([
        tradingApi.getSnapshot(),
        monitorApi.getRisk(),
        monitorApi.getStatus(),
      ]);

      const snapJson = parsePayloadData<TradingSnapshotPayload>(snapPayload) || {};
      const riskJson = parsePayloadData<MonitorRiskPayload>(riskPayload) || {};
      const statusJson = parsePayloadData<Array<MonitorStatusPayload> | MonitorStatusPayload>(statusPayload);

      const balance = snapJson?.balance ?? {};
      const positions = Array.isArray(snapJson?.positions) ? snapJson.positions : [];
      const totalValue = Number(balance?.total_assets ?? 1250000);
      const dailyPnl = Number(balance?.daily_pnl ?? 12500);
      const holdValue = Number(balance?.market_value ?? 980000);
      const cash = Number(balance?.available_cash ?? 270000);

      const assets: AssetEntry[] = [
        {
          title: '总资产',
          value: `¥${totalValue.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`,
          icon: <Wallet className="h-4 w-4" />,
        },
        {
          title: '今日盈亏',
          value: `${dailyPnl >= 0 ? '+' : ''}¥${dailyPnl.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`,
          trend: `${((dailyPnl / Math.max(totalValue, 1)) * 100).toFixed(2)}%`,
          trendIsUp: dailyPnl >= 0,
          icon: <TrendingUp className="h-4 w-4" />,
        },
        {
          title: '持仓市值',
          value: `¥${holdValue.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`,
          icon: <BarChart className="h-4 w-4" />,
        },
        {
          title: '可用资金',
          value: `¥${cash.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`,
          icon: <Layers className="h-4 w-4" />,
        },
      ];

      const agents: AgentEntry[] = [
        { id: 'fundamental', name: '基本面分析员', role: '宏观分析', description: '对宏观经济与行业估值进行分析。' },
        { id: 'technical', name: '技术面分析员', role: '图表指标', description: '跟踪价格行为、趋势结构和量价关系。' },
        { id: 'news', name: '新闻分析员', role: '事件驱动', description: '解析财经新闻、公告和政策冲击。' },
        { id: 'sentiment', name: '情绪分析员', role: '舆情追踪', description: '监控社交平台与媒体情绪变化。' },
        { id: 'trader', name: '交易决策者', role: '订单执行', description: '将策略建议转换为可执行交易指令。' },
        { id: 'risk', name: '风控经理', role: '风险控制', description: '评估仓位风险、回撤风险与执行约束。' },
      ];

      const stratRaw = snapJson?.strategies;
      const strategies: StrategyEntry[] =
        Array.isArray(stratRaw) && stratRaw.length > 0
          ? stratRaw.map((s: TradingStrategyPayload) => ({
              name: s.name ?? '未知',
              score: Math.round((s.quality_score ?? 0.7) * 100),
              status: s.status ?? '激活',
              trend: s.daily_return ? `${(s.daily_return * 100).toFixed(1)}%` : '0.0%',
            }))
          : positions.slice(0, 5).map((p: TradingPositionPayload) => {
              const marketValue = Number(p?.market_value ?? 0);
              const unrealizedPnl = Number(p?.unrealized_pnl ?? 0);
              const trend = marketValue > 0 ? `${((unrealizedPnl / marketValue) * 100).toFixed(1)}%` : '0.0%';
              const score = Math.max(30, Math.min(99, Math.round(60 + (unrealizedPnl >= 0 ? 20 : -10))));
              return {
                name: p?.ticker ?? '未知',
                score,
                status: '持仓',
                trend: `${unrealizedPnl >= 0 ? '+' : ''}${trend}`,
              };
            });

      const alerts: AlertEntry[] = [];
      const drawdown = Number(riskJson?.max_drawdown_current ?? 0.024);
      if (drawdown > 0.05) {
        alerts.push({ level: '高', time: new Date().toLocaleTimeString(), msg: `回撤 ${(drawdown * 100).toFixed(1)}% 接近阈值。` });
      }
      if (Array.isArray(statusJson)) {
        statusJson.forEach((channel) => {
          if (String(channel.status ?? '').toLowerCase() === 'offline') {
            alerts.push({ level: '中', time: new Date().toLocaleTimeString(), msg: `通道 ${channel.name} 已离线。` });
          }
        });
      }
      if (!alerts.length) {
        alerts.push({ level: '低', time: new Date().toLocaleTimeString(), msg: '所有系统运行正常。' });
      }

      setState({
        assets,
        agents,
        strategies,
        alerts,
        lastUpdated: new Date().toLocaleString(),
        loading: false,
        error: null,
      });
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : 'unknown error';
      setState({
        ...fallbackData,
        lastUpdated: `${new Date().toLocaleString()} (fallback)`,
        loading: false,
        error: errMsg,
      });
    }
  }, []);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  return (
    <div className="flex flex-col gap-6 p-6">
      <div className="flex items-center justify-between">
        <div className="flex flex-col">
          <h1 className="font-orbitron text-2xl font-black uppercase tracking-widest text-white">指挥中心</h1>
          <p className="text-xs text-info-gray/60 uppercase tracking-tighter">
            统一监控视图 - {state.lastUpdated}
            {state.loading && <Loader2 className="inline h-3 w-3 animate-spin ml-2 text-neon-cyan" />}
          </p>
        </div>
        <div className="flex gap-3">
          <Button variant="outline" size="sm" className="gap-2" onClick={() => void fetchData()}>
            <RefreshCcw className={cn('h-3.5 w-3.5', state.loading && 'animate-spin')} />
            <span>刷新</span>
          </Button>
          <Button variant="default" size="sm" className="gap-2">
            <Play className="h-3.5 w-3.5" />
            <span>全部启动</span>
          </Button>
          <Button variant="destructive" size="sm" className="gap-2">
            <Square className="h-3.5 w-3.5" />
            <span>紧急停机</span>
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {state.assets.map((asset, idx) => (
          <StatusCard key={idx} {...asset} />
        ))}
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        <div className="lg:col-span-8">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="flex items-center gap-2 font-orbitron text-xs font-bold uppercase tracking-widest text-neon-cyan">
              <Activity className="h-3.5 w-3.5" /> AI 智能体集群
            </h2>
            <Badge variant="outline" className="text-[9px]">{state.agents.length} 个智能体</Badge>
          </div>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {state.agents.map((agent) => (
              <AgentCard key={agent.id} {...agent} />
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-6 lg:col-span-4">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2">
                <Zap className="h-3.5 w-3.5" /> 激活策略矩阵
              </CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              {state.strategies.map((strategy, idx) => (
                <div key={idx} className="flex items-center justify-between border-b border-border/50 pb-2 last:border-0 last:pb-0">
                  <div className="flex flex-col">
                    <span className="text-xs font-bold text-white/90">{strategy.name}</span>
                    <span className="text-[9px] uppercase text-info-gray/50">评分: {strategy.score} | {strategy.status}</span>
                  </div>
                  <span className={cn('text-xs font-mono', strategy.trend.startsWith('+') ? 'text-up-green' : 'text-down-red')}>
                    {strategy.trend}
                  </span>
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
              {state.alerts.map((alert, idx) => (
                <div key={idx} className="flex gap-3 border-l-2 border-border pl-3">
                  <div className="flex flex-col gap-0.5">
                    <div className="flex items-center gap-2">
                      <span
                        className={cn(
                          'text-[9px] font-bold uppercase px-1 rounded-sm',
                          alert.level === '高'
                            ? 'bg-down-red/20 text-down-red'
                            : alert.level === '中'
                              ? 'bg-warn-gold/20 text-warn-gold'
                              : 'bg-info-gray/20 text-info-gray',
                        )}
                      >
                        {alert.level}
                      </span>
                      <span className="text-[9px] font-mono text-info-gray/40">{alert.time}</span>
                    </div>
                    <p className="text-[11px] text-info-gray/80 leading-tight">{alert.msg}</p>
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
