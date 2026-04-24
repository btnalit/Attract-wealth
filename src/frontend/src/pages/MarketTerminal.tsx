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
import { monitorApi, systemApi, tradingApi } from '../services/api';

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
  total_requests?: number | null;
  success_rate?: number | null;
  avg_latency_ms?: number | null;
  recent_fields?: string[];
  last_fields?: string[];
  providers?: Array<{
    name?: string;
    display_name?: string;
    enabled?: boolean;
    current?: boolean;
  }>;
}

interface KlinePoint {
  ts: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

interface DirectOrderResult {
  order?: {
    id?: string;
    order_id?: string;
    local_order_id?: string;
    broker_order_id?: string;
    status?: string;
  };
  trace?: {
    trace_id?: string;
    request_id?: string;
    idempotency_key?: string;
  };
  idempotency_key?: string;
  request_id?: string;
  message?: string;
  [key: string]: unknown;
}

const toNumber = (value: unknown): number | null => {
  if (value === null || value === undefined) {
    return null;
  }
  if (typeof value === 'string' && value.trim() === '') {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

const normalizeOptionalPercent = (value: unknown): number | null => {
  const numeric = toNumber(value);
  if (numeric === null) {
    return null;
  }
  const percent = numeric >= -1 && numeric <= 1 ? numeric * 100 : numeric;
  return Number(percent.toFixed(2));
};

const formatOptionalPercent = (value: number | null, signed = false): string => {
  if (value === null) {
    return '--';
  }
  const prefix = signed && value >= 0 ? '+' : '';
  return `${prefix}${value.toFixed(2)}%`;
};

const formatOptionalLatency = (value: number | null): string => {
  if (value === null) {
    return '--';
  }
  return `${Number.isInteger(value) ? value.toFixed(0) : value.toFixed(2)} ms`;
};

const toTimestamp = (value: unknown): number => {
  if (typeof value === 'number' && Number.isFinite(value)) {
    if (value > 1_000_000_000_000) {
      return value;
    }
    if (value > 1_000_000_000) {
      return value * 1000;
    }
    const asDate = String(Math.trunc(value));
    if (asDate.length === 8) {
      const y = Number(asDate.slice(0, 4));
      const m = Number(asDate.slice(4, 6));
      const d = Number(asDate.slice(6, 8));
      const ts = Date.UTC(y, Math.max(0, m - 1), d);
      return Number.isFinite(ts) ? ts : 0;
    }
  }
  if (typeof value === 'string') {
    const trimmed = value.trim();
    if (!trimmed) {
      return 0;
    }
    const parsed = Date.parse(trimmed);
    if (!Number.isNaN(parsed)) {
      return parsed;
    }
    if (/^\d{8}$/.test(trimmed)) {
      const y = Number(trimmed.slice(0, 4));
      const m = Number(trimmed.slice(4, 6));
      const d = Number(trimmed.slice(6, 8));
      const ts = Date.UTC(y, Math.max(0, m - 1), d);
      return Number.isFinite(ts) ? ts : 0;
    }
  }
  return 0;
};

const normalizeKline = (payload: unknown): KlinePoint[] => {
  const raw = payload && typeof payload === 'object' && 'data' in payload
    ? (payload as { data?: unknown }).data
    : payload;
  if (!Array.isArray(raw)) {
    return [];
  }

  const points: KlinePoint[] = [];
  for (const item of raw) {
    if (Array.isArray(item) && item.length >= 5) {
      const ts = toTimestamp(item[0]);
      const open = toNumber(item[1]);
      const close = toNumber(item[2]);
      const high = toNumber(item[3]);
      const low = toNumber(item[4]);
      if (ts > 0 && open !== null && close !== null && high !== null && low !== null) {
        points.push({ ts, open, high, low, close });
      }
      continue;
    }

    if (item && typeof item === 'object') {
      const row = item as Record<string, unknown>;
      const ts = toTimestamp(row.ts ?? row.timestamp ?? row.date ?? row.time ?? row.trade_date ?? row.datetime);
      const open = toNumber(row.open ?? row.o);
      const high = toNumber(row.high ?? row.h);
      const low = toNumber(row.low ?? row.l);
      const close = toNumber(row.close ?? row.c ?? row.price);
      if (ts > 0 && open !== null && high !== null && low !== null && close !== null) {
        points.push({ ts, open, high, low, close });
      }
    }
  }
  return points.sort((a, b) => a.ts - b.ts);
};

export const MarketTerminal: FC = () => {
  const [ticker, setTicker] = useState('sh600000');
  const [searchInput, setSearchInput] = useState('sh600000');
  const [quote, setQuote] = useState<QuoteData | null>(null);
  const [loading, setLoading] = useState(false);
  const [switchingProvider, setSwitchingProvider] = useState(false);
  const [health, setHealth] = useState<HealthData | null>(null);
  const [kline, setKline] = useState<KlinePoint[]>([]);
  const [klineError, setKlineError] = useState('');
  const [buyPrice, setBuyPrice] = useState('');
  const [buyQuantity, setBuyQuantity] = useState('');
  const [sellPrice, setSellPrice] = useState('');
  const [sellQuantity, setSellQuantity] = useState('');
  const [orderSubmittingSide, setOrderSubmittingSide] = useState<'BUY' | 'SELL' | null>(null);
  const [orderError, setOrderError] = useState('');
  const [orderSuccess, setOrderSuccess] = useState('');
  const [lastOrderResult, setLastOrderResult] = useState<DirectOrderResult | null>(null);

  const fetchQuote = useCallback(async (symbol: string) => {
    setLoading(true);
    setKlineError('');
    try {
      const [quoteResult, healthResult, klineResult] = await Promise.allSettled([
        monitorApi.getQuote<Record<string, unknown>>(symbol),
        monitorApi.getDataHealth<Record<string, unknown>>(),
        monitorApi.getKline<unknown>(symbol, 120),
      ]);

      if (quoteResult.status === 'fulfilled') {
        const quotePayload = quoteResult.value;
        const quoteData = (quotePayload && typeof quotePayload === 'object' && 'data' in quotePayload)
          ? (quotePayload as { data?: QuoteData }).data
          : (quotePayload as QuoteData | null);
        setQuote(quoteData ?? null);
      } else {
        setQuote(null);
      }

      if (healthResult.status === 'fulfilled') {
        const rawHealth = healthResult.value;
        const healthData: HealthData =
          rawHealth && typeof rawHealth === 'object' && 'data' in rawHealth
            ? ((rawHealth as { data?: HealthData }).data ?? {})
            : ((rawHealth as HealthData) ?? {});
        const successRatePercent = normalizeOptionalPercent(healthData?.success_rate);
        const avgLatency = toNumber(healthData?.avg_latency_ms);
        setHealth({
          ...healthData,
          success_rate: successRatePercent,
          avg_latency_ms: avgLatency,
          recent_fields: healthData?.recent_fields || healthData?.last_fields || [],
          providers: Array.isArray(healthData?.providers) ? healthData.providers : [],
        });
      } else {
        setHealth({
          provider: '',
          current_provider: '',
          current_provider_display_name: '',
          total_requests: null,
          success_rate: null,
          avg_latency_ms: null,
          recent_fields: [],
          providers: [],
        });
      }

      if (klineResult.status === 'fulfilled') {
        setKline(normalizeKline(klineResult.value));
      } else {
        setKline([]);
        setKlineError(String(klineResult.reason ?? 'K 线加载失败'));
      }
    } catch (err) {
      console.warn('[MarketTerminal] Failed to fetch data:', err);
      setQuote(null);
      setKline([]);
      setKlineError(String(err));
      setHealth({
        provider: '',
        current_provider: '',
        current_provider_display_name: '',
        total_requests: null,
        success_rate: null,
        avg_latency_ms: null,
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

  useEffect(() => {
    const latestPrice = Number(quote?.price);
    if (!Number.isFinite(latestPrice) || latestPrice <= 0) {
      return;
    }
    const displayPrice = latestPrice.toFixed(2);
    setBuyPrice(displayPrice);
    setSellPrice(displayPrice);
  }, [quote?.price, ticker]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchInput.trim()) return;
    setTicker(searchInput.trim().toLowerCase());
  };

  const quoteChangePct = normalizeOptionalPercent(quote?.change_pct);
  const quoteChangeState = quoteChangePct === null ? 'neutral' : quoteChangePct >= 0 ? 'up' : 'down';
  const successRate = normalizeOptionalPercent(health?.success_rate);
  const successRateProgress = successRate === null ? 0 : Math.max(0, Math.min(100, successRate));
  const latencyMs = toNumber(health?.avg_latency_ms);
  const recentFields = useMemo(() => health?.recent_fields || health?.last_fields || [], [health]);
  const providers = useMemo(() => (Array.isArray(health?.providers) ? health?.providers : []), [health]);
  const currentProviderDisplay = useMemo(
    () => String(health?.current_provider_display_name || health?.provider || '--'),
    [health],
  );
  const switchTarget = useMemo(() => {
    return providers.find((item) => Boolean(item?.enabled) && !Boolean(item?.current))?.name ?? '';
  }, [providers]);

  const klinePath = useMemo(() => {
    if (kline.length < 2) {
      return '';
    }
    const width = 1000;
    const height = 360;
    const closes = kline.map((item) => item.close);
    const minClose = Math.min(...closes);
    const maxClose = Math.max(...closes);
    const range = Math.max(1e-6, maxClose - minClose);
    return kline
      .map((item, index) => {
        const x = (index / Math.max(1, kline.length - 1)) * width;
        const y = height - ((item.close - minClose) / range) * height;
        return `${index === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`;
      })
      .join(' ');
  }, [kline]);

  const klineAreaPath = useMemo(() => {
    if (kline.length < 2 || !klinePath) {
      return '';
    }
    const width = 1000;
    const height = 360;
    return `${klinePath} L ${width} ${height} L 0 ${height} Z`;
  }, [kline, klinePath]);

  const lastKlinePoint = useMemo(() => (kline.length > 0 ? kline[kline.length - 1] : null), [kline]);

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

  const resolveOrderRef = (result: DirectOrderResult): string => {
    const order = result.order ?? {};
    return String(
      order.local_order_id ||
        order.order_id ||
        order.id ||
        result.request_id ||
        result.idempotency_key ||
        '--',
    );
  };

  const handleSubmitOrder = async (side: 'BUY' | 'SELL') => {
    const rawPrice = side === 'BUY' ? buyPrice : sellPrice;
    const rawQuantity = side === 'BUY' ? buyQuantity : sellQuantity;
    const price = Number(rawPrice);
    const quantity = Number(rawQuantity);

    setOrderError('');
    setOrderSuccess('');

    if (!Number.isFinite(price) || price <= 0) {
      setOrderError(`${side === 'BUY' ? '买入' : '卖出'}价格必须大于 0。`);
      return;
    }
    if (!Number.isFinite(quantity) || quantity <= 0 || !Number.isInteger(quantity)) {
      setOrderError(`${side === 'BUY' ? '买入' : '卖出'}数量必须是大于 0 的整数。`);
      return;
    }

    const idempotencyKey = `${ticker.toLowerCase()}-${side.toLowerCase()}-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
    setOrderSubmittingSide(side);
    try {
      const response = await tradingApi.placeDirectOrder<DirectOrderResult>({
        ticker: ticker.toLowerCase(),
        side,
        quantity,
        qty: quantity,
        price,
        order_type: 'limit',
        idempotency_key: idempotencyKey,
        memo: `MarketTerminal:${side}`,
      });
      const result = (response && typeof response === 'object' && 'data' in response)
        ? ((response as { data?: DirectOrderResult }).data ?? {})
        : response;
      const resultStatus = String(result.order?.status ?? '').toLowerCase() || 'accepted';
      const orderRef = resolveOrderRef(result);
      setLastOrderResult(result);
      setOrderSuccess(`${side === 'BUY' ? '买入' : '卖出'}委托已提交，状态：${resultStatus}，订单：${orderRef}`);
      await fetchQuote(ticker);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setOrderError(`${side === 'BUY' ? '买入' : '卖出'}下单失败：${message}`);
    } finally {
      setOrderSubmittingSide(null);
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
                <span
                  className={cn(
                    'font-mono text-sm font-bold',
                    quoteChangeState === 'neutral' ? 'text-info-gray' : quoteChangeState === 'up' ? 'text-up-green' : 'text-down-red',
                  )}
                >
                  {quote.price?.toFixed(2) || '--'}
                </span>
                <span
                  className={cn(
                    'text-[9px] font-bold',
                    quoteChangeState === 'neutral'
                      ? 'text-info-gray/70'
                      : quoteChangeState === 'up'
                        ? 'text-up-green/80'
                        : 'text-down-red/80',
                  )}
                >
                  {formatOptionalPercent(quoteChangePct, true)}
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
              {loading && kline.length === 0 ? (
                <div className="flex items-center gap-2 text-info-gray/70">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  <span className="text-xs">加载 K 线中...</span>
                </div>
              ) : klineError ? (
                <div className="flex flex-col items-center gap-2 text-down-red/80">
                  <LineChart className="h-10 w-10 stroke-[1px]" />
                  <span className="text-xs">K 线加载失败</span>
                  <span className="max-w-[480px] text-center text-[10px] text-info-gray/60">{klineError}</span>
                </div>
              ) : kline.length < 2 ? (
                <div className="flex flex-col items-center gap-2 text-info-gray/50">
                  <LineChart className="h-10 w-10 stroke-[1px]" />
                  <span className="text-xs">暂无可视化 K 线数据</span>
                </div>
              ) : (
                <div className="h-full w-full px-4 py-6">
                  <svg viewBox="0 0 1000 360" className="h-full w-full">
                    <defs>
                      <linearGradient id="kline-fill" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="rgba(0,240,255,0.35)" />
                        <stop offset="100%" stopColor="rgba(0,240,255,0)" />
                      </linearGradient>
                    </defs>
                    {[0, 1, 2, 3, 4].map((line) => (
                      <line
                        key={line}
                        x1={0}
                        x2={1000}
                        y1={(line / 4) * 360}
                        y2={(line / 4) * 360}
                        stroke="rgba(148,163,184,0.15)"
                        strokeWidth="1"
                      />
                    ))}
                    {klineAreaPath && <path d={klineAreaPath} fill="url(#kline-fill)" />}
                    <path d={klinePath} stroke="#00f0ff" strokeWidth="2.5" fill="none" />
                  </svg>
                </div>
              )}
            </div>

            <div
              className="absolute inset-0 pointer-events-none opacity-[0.03]"
              style={{
                backgroundImage: 'linear-gradient(var(--border) 1px, transparent 1px), linear-gradient(90deg, var(--border) 1px, transparent 1px)',
                backgroundSize: '40px 40px',
              }}
            />
            <div className="absolute right-4 top-4 z-10 rounded border border-border bg-bg-card/80 px-3 py-2 text-[10px] font-mono text-info-gray/80">
              {lastKlinePoint ? (
                <>
                  <div>Latest Close: {lastKlinePoint.close.toFixed(2)}</div>
                  <div>{new Date(lastKlinePoint.ts).toLocaleString('zh-CN')}</div>
                </>
              ) : (
                <div>无最新 K 线</div>
              )}
            </div>
          </div>

          <div className="flex h-[240px] flex-col border-t border-border bg-bg-card/30">
            <div className="flex h-8 items-center border-b border-border bg-bg-card/50 px-4">
              <span className="text-[10px] font-bold uppercase tracking-widest text-neon-cyan">执行面板</span>
            </div>
            <div className="flex h-full flex-col p-4 gap-3">
              <div className="grid grid-cols-2 gap-4 flex-1">
                <div className="flex flex-col gap-3">
                  <div className="grid grid-cols-2 gap-2">
                    <div className="flex flex-col gap-1">
                      <label className="text-[9px] uppercase text-info-gray/60 font-bold">限价</label>
                      <input
                        type="number"
                        step="0.01"
                        min="0"
                        value={buyPrice}
                        onChange={(e) => setBuyPrice(e.target.value)}
                        className="h-8 border border-border bg-bg-primary/50 px-2 text-xs font-mono text-white outline-none focus:border-neon-cyan/50"
                      />
                    </div>
                    <div className="flex flex-col gap-1">
                      <label className="text-[9px] uppercase text-info-gray/60 font-bold">数量</label>
                      <input
                        type="number"
                        step="1"
                        min="1"
                        value={buyQuantity}
                        onChange={(e) => setBuyQuantity(e.target.value)}
                        placeholder="100"
                        className="h-8 border border-border bg-bg-primary/50 px-2 text-xs font-mono text-white outline-none focus:border-neon-cyan/50"
                      />
                    </div>
                  </div>
                  <Button
                    variant="default"
                    className="mt-auto h-10 w-full bg-up-green/10 text-up-green border-up-green/40 hover:bg-up-green/20"
                    disabled={Boolean(orderSubmittingSide)}
                    onClick={() => void handleSubmitOrder('BUY')}
                  >
                    {orderSubmittingSide === 'BUY' ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <ArrowUpRight className="mr-2 h-4 w-4" />
                    )}
                    买入 ({ticker.toUpperCase()})
                  </Button>
                </div>

                <div className="flex flex-col gap-3">
                  <div className="grid grid-cols-2 gap-2">
                    <div className="flex flex-col gap-1">
                      <label className="text-[9px] uppercase text-info-gray/60 font-bold">限价</label>
                      <input
                        type="number"
                        step="0.01"
                        min="0"
                        value={sellPrice}
                        onChange={(e) => setSellPrice(e.target.value)}
                        className="h-8 border border-border bg-bg-primary/50 px-2 text-xs font-mono text-white outline-none focus:border-down-red/50"
                      />
                    </div>
                    <div className="flex flex-col gap-1">
                      <label className="text-[9px] uppercase text-info-gray/60 font-bold">数量</label>
                      <input
                        type="number"
                        step="1"
                        min="1"
                        value={sellQuantity}
                        onChange={(e) => setSellQuantity(e.target.value)}
                        placeholder="100"
                        className="h-8 border border-border bg-bg-primary/50 px-2 text-xs font-mono text-white outline-none focus:border-down-red/50"
                      />
                    </div>
                  </div>
                  <Button
                    variant="destructive"
                    className="mt-auto h-10 w-full bg-down-red/10 text-down-red border-down-red/40 hover:bg-down-red/20"
                    disabled={Boolean(orderSubmittingSide)}
                    onClick={() => void handleSubmitOrder('SELL')}
                  >
                    {orderSubmittingSide === 'SELL' ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <ArrowDownLeft className="mr-2 h-4 w-4" />
                    )}
                    卖出 ({ticker.toUpperCase()})
                  </Button>
                </div>
              </div>

              <div className="min-h-[54px] rounded border border-border/60 bg-bg-primary/30 px-3 py-2 text-[10px] font-mono">
                {orderError ? (
                  <div className="text-down-red">{orderError}</div>
                ) : orderSuccess ? (
                  <div className="space-y-1 text-up-green">
                    <div>{orderSuccess}</div>
                    {lastOrderResult?.trace?.trace_id && (
                      <div className="text-info-gray/70">trace_id: {lastOrderResult.trace.trace_id}</div>
                    )}
                  </div>
                ) : (
                  <div className="text-info-gray/60">
                    输入价格与数量后可直接下单，订单将通过统一 API 层提交到后端守门链路。
                  </div>
                )}
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
                  <span className={cn('font-bold', successRate === null ? 'text-info-gray/70' : 'text-up-green')}>
                    {formatOptionalPercent(successRate)}
                  </span>
                </div>
                <div className="h-1 w-full bg-bg-hover rounded-full overflow-hidden">
                  <div
                    className={cn(
                      'h-full transition-all duration-1000',
                      successRate === null ? 'bg-info-gray/40' : 'bg-up-green',
                    )}
                    style={{ width: `${successRateProgress}%` }}
                  />
                </div>
              </div>

              <div className="flex justify-between text-[9px] uppercase font-mono">
                <span className="text-info-gray/50">平均延迟</span>
                <span
                  className={cn(
                    'font-bold',
                    latencyMs === null ? 'text-info-gray/70' : latencyMs > 100 ? 'text-warn-gold' : 'text-up-green',
                  )}
                >
                  {formatOptionalLatency(latencyMs)}
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
