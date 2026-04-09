import { useState, useEffect, useCallback, FC } from 'react';
import { 
  Search, ChevronDown, 
  ArrowUpRight, ArrowDownLeft, LineChart, Loader2, RefreshCcw, Zap
} from 'lucide-react';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { cn } from '../lib/utils';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

export const MarketTerminal: FC = () => {
  const [ticker, setTicker] = useState('sh600000');
  const [searchInput, setSearchInput] = useState('sh600000');
  const [quote, setQuote] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  const fetchQuote = useCallback(async (symbol: string) => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/v1/monitor/quote/${symbol}`);
      if (res.ok) {
        const json = await res.json();
        setQuote(json.data);
      }
    } catch (err) {
      console.warn('[MarketTerminal] Failed to fetch quote:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchQuote(ticker); }, [ticker, fetchQuote]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (searchInput.trim()) setTicker(searchInput.trim().toLowerCase());
  };

  return (
    <div className="flex h-full flex-col overflow-hidden bg-bg-primary text-gray-300 font-mono">
      {/* Top Search & Instrument Bar */}
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
              <span className="text-[10px] font-bold text-white uppercase tracking-wider">{quote?.name || ticker} / A 股市场</span>
              <span className="text-[9px] text-info-gray/60">实时数据 {loading && <Loader2 className="inline h-2 w-2 animate-spin ml-1" />}</span>
            </div>
            <div className="h-6 w-[1px] bg-border" />
            {quote ? (
              <div className="flex flex-col">
                <span className={cn("font-mono text-sm font-bold", quote.change_pct >= 0 ? "text-up-green" : "text-down-red")}>
                  {quote.price?.toFixed(2) || '--'}
                </span>
                <span className={cn("text-[9px] font-bold", quote.change_pct >= 0 ? "text-up-green/80" : "text-down-red/80")}>
                  {quote.change_pct >= 0 ? '+' : ''}{quote.change_pct?.toFixed(2)}%
                </span>
              </div>
            ) : <span className="text-[10px] text-info-gray">无数据</span>}
          </div>
        </form>

        <div className="flex items-center gap-3">
          <div className="flex h-8 items-center gap-1.5 rounded-sm border border-border px-3 bg-bg-primary/30">
            <Zap className="h-3 w-3 text-warn-gold" />
            <span className="text-[9px] font-bold uppercase text-info-gray">数据源: AKSHARE</span>
            <ChevronDown className="h-3 w-3" />
          </div>
          <Button variant="outline" size="sm" className="h-8 px-2" onClick={() => fetchQuote(ticker)}>
            <RefreshCcw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
          </Button>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* Left Area: Chart & Order Form */}
        <div className="flex flex-[3] flex-col border-r border-border">
          {/* Main Chart Placeholder */}
          <div className="relative flex-1 bg-bg-primary overflow-hidden">
            <div className="absolute left-4 top-4 z-10 flex gap-2">
              <Badge variant="outline" className="bg-bg-card/80 backdrop-blur-md">成交量: {quote?.volume || '--'}</Badge>
              <Badge variant="outline" className="bg-bg-card/80 backdrop-blur-md">成交额: {quote?.turnover || '--'}</Badge>
            </div>
            
            <div className="flex h-full w-full items-center justify-center">
              <div className="flex flex-col items-center gap-4 text-info-gray/20">
                <LineChart className="h-24 w-24 stroke-[1px]" />
                <span className="font-orbitron text-sm font-bold uppercase tracking-[0.4em]">TradingView 行情图表</span>
                <span className="text-[10px] font-mono">[ 已连接到 {ticker.toUpperCase()} ]</span>
              </div>
            </div>
            
            <div className="absolute inset-0 pointer-events-none opacity-[0.03]" 
                 style={{ backgroundImage: 'linear-gradient(var(--border) 1px, transparent 1px), linear-gradient(90deg, var(--border) 1px, transparent 1px)', backgroundSize: '40px 40px' }} 
            />
          </div>

          {/* Bottom Order Panel */}
          <div className="flex h-[240px] flex-col border-t border-border bg-bg-card/30">
            <div className="flex h-8 items-center border-b border-border bg-bg-card/50 px-4">
              <span className="text-[10px] font-bold uppercase tracking-widest text-neon-cyan">执行面板</span>
            </div>
            <div className="grid grid-cols-2 gap-4 p-4 h-full">
              {/* Buy Form */}
              <div className="flex flex-col gap-3">
                <div className="grid grid-cols-2 gap-2">
                  <div className="flex flex-col gap-1">
                    <label className="text-[9px] uppercase text-info-gray/60 font-bold">限价</label>
                    <input type="text" defaultValue={quote?.price} className="h-8 border border-border bg-bg-primary/50 px-2 text-xs font-mono text-white outline-none focus:border-neon-cyan/50" />
                  </div>
                  <div className="flex flex-col gap-1">
                    <label className="text-[9px] uppercase text-info-gray/60 font-bold">数量</label>
                    <input type="text" placeholder="0.00" className="h-8 border border-border bg-bg-primary/50 px-2 text-xs font-mono text-white outline-none focus:border-neon-cyan/50" />
                  </div>
                </div>
                <Button variant="default" className="mt-auto h-10 w-full bg-up-green/10 text-up-green border-up-green/40 hover:bg-up-green/20">
                  <ArrowUpRight className="mr-2 h-4 w-4" />
                  买入开多 ({ticker.toUpperCase()})
                </Button>
              </div>

              {/* Sell Form */}
              <div className="flex flex-col gap-3">
                <div className="grid grid-cols-2 gap-2">
                  <div className="flex flex-col gap-1">
                    <label className="text-[9px] uppercase text-info-gray/60 font-bold">限价</label>
                    <input type="text" defaultValue={quote?.price} className="h-8 border border-border bg-bg-primary/50 px-2 text-xs font-mono text-white outline-none focus:border-down-red/50" />
                  </div>
                  <div className="flex flex-col gap-1">
                    <label className="text-[9px] uppercase text-info-gray/60 font-bold">数量</label>
                    <input type="text" placeholder="0.00" className="h-8 border border-border bg-bg-primary/50 px-2 text-xs font-mono text-white outline-none focus:border-down-red/50" />
                  </div>
                </div>
                <Button variant="destructive" className="mt-auto h-10 w-full bg-down-red/10 text-down-red border-down-red/40 hover:bg-down-red/20">
                  <ArrowDownLeft className="mr-2 h-4 w-4" />
                  卖出开空 ({ticker.toUpperCase()})
                </Button>
              </div>
            </div>
          </div>
        </div>

        {/* Right Area: Instrument Info & Indicators */}
        <div className="flex flex-1 flex-col overflow-y-auto bg-bg-card/30 custom-scrollbar">
          <div className="p-4 border-b border-border">
            <h3 className="mb-4 text-[10px] font-bold uppercase tracking-[0.2em] text-neon-cyan">技术脉搏</h3>
            <div className="flex flex-col gap-3">
              <Indicator label="RSI (14)" value="54.21" percent={54.21} />
              <Indicator label="MACD" value="+1.24" color="text-up-green" />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

const Indicator: FC<any> = ({ label, value, percent, color = "text-white" }) => (
  <div className="flex flex-col gap-1">
    <div className="flex justify-between text-[10px] uppercase">
      <span className="text-info-gray/60">{label}</span>
      <span className={cn("font-bold", color)}>{value}</span>
    </div>
    {percent !== undefined && (
      <div className="h-1 w-full bg-bg-hover rounded-full overflow-hidden">
        <div className="h-full bg-neon-cyan" style={{ width: `${percent}%` }} />
      </div>
    )}
  </div>
);

export default MarketTerminal;
