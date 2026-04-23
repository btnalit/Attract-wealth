import { useCallback, useEffect, useMemo, useState, type FC } from 'react';
import {
  ArrowDownLeft,
  ArrowUpRight,
  Database,
  LineChart,
  Loader2,
  RefreshCcw,
  Search,
  Zap,
} from 'lucide-react';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { cn } from '../lib/utils';
import { monitorApi, systemApi } from '../services/api';

interface QuoteData {
  ticker?: string;
  name?: string;
  price?: number;
  change_pct?: number;
  amount?: number;
  turnover?: number;
  volume?: number;
  volume_chg?: number;
}

interface HealthData {
  provider?: string;
  current_provider?: string;
  current_provider_display_name?: string;
  total_requests?: number;
  success_rate?: number;
  avg_latency_ms?: number;
  recent_fields?: string[];
  last_fields?: string[];
  providers?: Array<{
    name?: string;
    display_name?: string;
    enabled?: boolean;
    current?: boolean;
  }>;
}

export const MarketTerminal: FC = () => {
  const [ticker, setTicker] = useState('sh600000');
  const [searchInput, setSearchInput] = useState('sh600000');
  const [quote, setQuote] = useState<QuoteData | null>(null);
  const [loading, setLoading] = useState(false);
  const [switchingProvider, setSwitchingProvider] = useState(false);
  const [health, setHealth] = useState<HealthData | null>(null);

  const fetchQuote = useCallback(async (symbol: string) => {
    setLoading(true);
    try {
      const [quoteResult, healthResult] = await Promise.allSettled([
        monitorApi.getQuote<Record<string, unknown>>(symbol),
        monitorApi.getDataHealth<Record<string, unknown>>(),
      ]);

      if (quoteResult.status === 'fulfilled') {
        const quotePayload = quoteResult.value;
        const quoteData = (quotePayload && typeof quotePayload === 'object' && 'data' in quotePayload)
          ? (quotePayload as { data?: QuoteData }).data
          : (quotePayload as QuoteData | null);
        setQuote(quoteData ?? null);
      }

      if (healthResult.status === 'fulfilled') {
        const rawHealth = healthResult.value;
        const healthData: HealthData =
          rawHealth && typeof rawHealth === 'object' && 'data' in rawHealth
            ? ((rawHealth as { data?: HealthData }).data ?? {})
            : ((rawHealth as HealthData) ?? {});
        const successRateRaw = Number(healthData?.success_rate ?? 0);
        const successRatePercent = successRateRaw <= 1 ? successRateRaw * 100 : successRateRaw;
        setHealth({
          ...healthData,
          success_rate: Number(successRatePercent.toFixed(2)),
          recent_fields: healthData?.recent_fields || healthData?.last_fields || [],
          providers: Array.isArray(healthData?.providers) ? healthData.providers : [],
        });
      } else {
        setHealth({
          provider: '',
          current_provider: '',
          current_provider_display_name: '',
          total_requests: 0,
          success_rate: 0,
          avg_latency_ms: 0,
          recent_fields: [],
          providers: [],
        });
      }
    } catch (err) {
      console.warn('[MarketTerminal] Failed to fetch data:', err);
      setHealth({
        provider: '',
        current_provider: '',
        current_provider_display_name: '',
        total_requests: 0,
        success_rate: 0,
        avg_latency_ms: 0,
        recent_fields: [],
        providers: [],
      });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchQuote(ticker);
  }, [ticker, fetchQuote]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchInput.trim()) return;
    setTicker(searchInput.trim().toLowerCase());
  };

  const successRate = Number(health?.success_rate ?? 0);
  const recentFields = useMemo(() => health?.recent_fields || health?.last_fields || [], [health]);
  const providers = useMemo(() => (Array.isArray(health?.providers) ? health?.providers : []), [health]);
  const currentProviderDisplay = useMemo(
    () => String(health?.current_provider_display_name || health?.provider || '--'),
    [health],
  );
  const switchTarget = useMemo(() => {
    return providers.find((item) => Boolean(item?.enabled) && !Boolean(item?.current))?.name ?? '';
  }, [providers]);

  const handleSwitchProvider = async () => {
    if (!switchTarget) {
      return;
    }
    setSwitchingProvider(true);
    try {
      await systemApi.switchDataflowProvider({
        provider: String(switchTarget),
        persist: true,
      });
      await fetchQuote(ticker);
    } catch (err) {
      console.warn('[MarketTerminal] Failed to switch provider:', err);
    } finally {
      setSwitchingProvider(false);
    }
  };

  return (
    <div className="flex h-full flex-col overflow-hidden bg-bg-primary text-gray-300 font-mono">
      <div className="flex items-center justify-between border-b border-border bg-bg-card/50 p-2 px-4 backdrop-blur-sm">
        <form onSubmit={handleSearch} className="flex items-center gap-6">
          <div className="flex h-8 items-center rounded-sm border border-border bg-bg-primary/50 px-3 transition-colors hover:border-neon-cyan/50 focus-within:border-neon-cyan/80">
            <Search className="h-3.5 w-3.5 text-info-gray/60" />
            <input
              type="text"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="搜索代码 (例如 sh600000)"
              className="ml-2 w-48 bg-transparent text-[10px] font-mono text-white outline-none placeholder:text-info-gray/40 uppercase"
            />
          </div>

          <div className="flex items-center gap-4">
            <div className="flex flex-col">
              <span className="text-[10px] font-bold text-white uppercase tracking-wider">
                {quote?.name || ticker} / A 股市场
              </span>
              <span className="text-[9px] text-info-gray/60">
                实时数据 {loading && <Loader2 className="inline h-2 w-2 animate-spin ml-1" />}
              </span>
            </div>
            <div className="h-6 w-[1px] bg-border" />
            {quote ? (
              <div className="flex flex-col">
                <span className={cn('font-mono text-sm font-bold', (quote.change_pct ?? 0) >= 0 ? 'text-up-green' : 'text-down-red')}>
                  {quote.price?.toFixed(2) || '--'}
                </span>
                <span className={cn('text-[9px] font-bold', (quote.change_pct ?? 0) >= 0 ? 'text-up-green/80' : 'text-down-red/80')}>
                  {(quote.change_pct ?? 0) >= 0 ? '+' : ''}{(quote.change_pct ?? 0).toFixed(2)}%
                </span>
              </div>
            ) : (
              <span className="text-[10px] text-info-gray">无数据</span>
            )}
          </div>
        </form>

        <div className="flex items-center gap-3">
          <div className="flex h-8 items-center gap-1.5 rounded-sm border border-border px-3 bg-bg-primary/30">
            <Zap className="h-3 w-3 text-warn-gold" />
            <span className="text-[9px] font-bold uppercase text-info-gray">数据源 {currentProviderDisplay}</span>
          </div>
          {switchTarget && (
            <Button variant="outline" size="sm" className="h-8 px-2 text-[10px]" onClick={() => void handleSwitchProvider()} disabled={switchingProvider}>
              {switchingProvider ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : '切换源'}
            </Button>
          )}
          <Button variant="outline" size="sm" className="h-8 px-2" onClick={() => void fetchQuote(ticker)}>
            <RefreshCcw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} />
          </Button>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        <div className="flex flex-[3] flex-col border-r border-border">
          <div className="relative flex-1 bg-bg-primary overflow-hidden">
            <div className="absolute left-4 top-4 z-10 flex gap-2">
              <Badge variant="outline" className="bg-bg-card/80 backdrop-blur-md">
                成交量 {quote?.volume ?? quote?.volume_chg ?? '--'}
              </Badge>
              <Badge variant="outline" className="bg-bg-card/80 backdrop-blur-md">
                成交额 {quote?.turnover ?? quote?.amount ?? '--'}
              </Badge>
            </div>

            <div className="flex h-full w-full items-center justify-center">
              <div className="flex flex-col items-center gap-4 text-info-gray/20">
                <LineChart className="h-24 w-24 stroke-[1px]" />
                <span className="font-orbitron text-sm font-bold uppercase tracking-[0.4em]">TradingView 行情图表</span>
                <span className="text-[10px] font-mono">[ 当前标的 {ticker.toUpperCase()} ]</span>
              </div>
            </div>

            <div
              className="absolute inset-0 pointer-events-none opacity-[0.03]"
              style={{
                backgroundImage: 'linear-gradient(var(--border) 1px, transparent 1px), linear-gradient(90deg, var(--border) 1px, transparent 1px)',
                backgroundSize: '40px 40px',
              }}
            />
          </div>

          <div className="flex h-[240px] flex-col border-t border-border bg-bg-card/30">
            <div className="flex h-8 items-center border-b border-border bg-bg-card/50 px-4">
              <span className="text-[10px] font-bold uppercase tracking-widest text-neon-cyan">执行面板</span>
            </div>
            <div className="grid grid-cols-2 gap-4 p-4 h-full">
              <div className="flex flex-col gap-3">
                <div className="grid grid-cols-2 gap-2">
                  <div className="flex flex-col gap-1">
                    <label className="text-[9px] uppercase text-info-gray/60 font-bold">限价</label>
                    <input type="text" defaultValue={quote?.price} className="h-8 border border-border bg-bg-primary/50 px-2 text-xs font-mono text-white outline-none focus:border-neon-cyan/50" />
                  </div>
                  <div className="flex flex-col gap-1">
                    <label className="text-[9px] uppercase text-info-gray/60 font-bold">数量</label>
                    <input type="text" placeholder="0" className="h-8 border border-border bg-bg-primary/50 px-2 text-xs font-mono text-white outline-none focus:border-neon-cyan/50" />
                  </div>
                </div>
                <Button variant="default" className="mt-auto h-10 w-full bg-up-green/10 text-up-green border-up-green/40 hover:bg-up-green/20">
                  <ArrowUpRight className="mr-2 h-4 w-4" /> 买入 ({ticker.toUpperCase()})
                </Button>
              </div>

              <div className="flex flex-col gap-3">
                <div className="grid grid-cols-2 gap-2">
                  <div className="flex flex-col gap-1">
                    <label className="text-[9px] uppercase text-info-gray/60 font-bold">限价</label>
                    <input type="text" defaultValue={quote?.price} className="h-8 border border-border bg-bg-primary/50 px-2 text-xs font-mono text-white outline-none focus:border-down-red/50" />
                  </div>
                  <div className="flex flex-col gap-1">
                    <label className="text-[9px] uppercase text-info-gray/60 font-bold">数量</label>
                    <input type="text" placeholder="0" className="h-8 border border-border bg-bg-primary/50 px-2 text-xs font-mono text-white outline-none focus:border-down-red/50" />
                  </div>
                </div>
                <Button variant="destructive" className="mt-auto h-10 w-full bg-down-red/10 text-down-red border-down-red/40 hover:bg-down-red/20">
                  <ArrowDownLeft className="mr-2 h-4 w-4" /> 卖出 ({ticker.toUpperCase()})
                </Button>
              </div>
            </div>
          </div>
        </div>

        <div className="flex flex-1 flex-col overflow-y-auto bg-bg-card/30 custom-scrollbar">
          <div className="p-4 border-b border-border bg-bg-primary/20">
            <div className="flex items-center gap-2 mb-4">
              <Database className="h-3 w-3 text-warn-gold" />
              <h3 className="text-[10px] font-bold uppercase tracking-[0.2em] text-white">{currentProviderDisplay} 健康度</h3>
            </div>

            <div className="space-y-4">
              <div className="flex justify-between text-[9px] uppercase font-mono">
                <span className="text-info-gray/50">请求总数</span>
                <span className="text-white">{health?.total_requests?.toLocaleString() || '--'}</span>
              </div>

              <div className="flex flex-col gap-1">
                <div className="flex justify-between text-[9px] uppercase font-mono mb-1">
                  <span className="text-info-gray/50">成功率</span>
                  <span className="text-up-green font-bold">{successRate.toFixed(2)}%</span>
                </div>
                <div className="h-1 w-full bg-bg-hover rounded-full overflow-hidden">
                  <div className="h-full bg-up-green transition-all duration-1000" style={{ width: `${Math.max(0, Math.min(100, successRate))}%` }} />
                </div>
              </div>

              <div className="flex justify-between text-[9px] uppercase font-mono">
                <span className="text-info-gray/50">平均延迟</span>
                <span className={cn('font-bold', Number(health?.avg_latency_ms || 0) > 100 ? 'text-warn-gold' : 'text-up-green')}>
                  {Number(health?.avg_latency_ms || 0)} ms
                </span>
              </div>

              <div className="flex flex-col gap-2">
                <span className="text-[9px] text-info-gray/50 uppercase font-mono">最近成功字段</span>
                <div className="flex flex-wrap gap-1.5">
                  {recentFields.length > 0 ? (
                    recentFields.map((field) => (
                      <span key={field} className="px-1.5 py-0.5 rounded-sm bg-bg-hover border border-border/50 text-[8px] font-mono text-info-gray/80">
                        {field}
                      </span>
                    ))
                  ) : (
                    <span className="text-[8px] text-info-gray/30 italic">暂无记录</span>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default MarketTerminal;
