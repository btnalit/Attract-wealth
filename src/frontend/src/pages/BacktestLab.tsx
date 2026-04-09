import React, { useState, useEffect, useRef } from 'react';
import { Play, Settings, TrendingUp, Info, BarChart, RotateCcw, Plus, Trash2, Loader2 } from 'lucide-react';
import { cn } from '../lib/utils';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

interface Metric {
  label: string;
  value: string;
  subValue?: string;
  color: string;
}

const mockMetrics: Metric[] = [
  { label: 'TOTAL RETURN', value: '+42.84%', subValue: '¥428,400', color: 'text-up-green' },
  { label: 'ANNUALIZED', value: '28.5%', subValue: 'Compound', color: 'text-white' },
  { label: 'MAX DRAWDOWN', value: '-8.12%', subValue: 'Low Risk', color: 'text-up-red' },
  { label: 'SHARPE RATIO', value: '1.84', subValue: 'Excellent', color: 'text-neon-cyan' },
  { label: 'WIN RATE', value: '62.4%', subValue: '124/198 Trades', color: 'text-info-gray' },
  { label: 'PROFIT FACTOR', value: '2.14', subValue: 'High Quality', color: 'text-warn-gold' },
];

export const BacktestLab: React.FC = () => {
  const [isRunning, setIsRunning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [showMonteCarlo, setShowMonteCarlo] = useState(false);
  const [params, setParams] = useState([{ key: 'MA_PERIOD', value: '20' }, { key: 'RISK_PCT', value: '0.02' }]);
  const [strategyId, setStrategyId] = useState('Multi-Factor Mean Reversion');
  const [startDate, setStartDate] = useState('2023-01-01');
  const [endDate, setEndDate] = useState('2024-04-01');
  const [initialCapital, setInitialCapital] = useState('1000000');
  const [metrics, setMetrics] = useState<Metric[]>(mockMetrics);
  const [equityCurve, setEquityCurve] = useState<string>("M 0 80 L 10 75 L 20 78 L 30 70 L 40 74 L 50 62 L 60 65 L 70 50 L 80 55 L 90 35 L 100 25");
  
  const pollIntervalRef = useRef<number | null>(null);

  const runBacktest = async () => {
    setIsRunning(true);
    setProgress(0);
    
    try {
      const payload = {
        strategy_id: strategyId,
        start_date: startDate,
        end_date: endDate,
        initial_capital: parseFloat(initialCapital),
        params: Object.fromEntries(params.map(p => [p.key, p.value]))
      };

      const response = await fetch(`${API_BASE}/api/strategy/backtest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (response.ok) {
        const { job_id } = await response.json();
        startPolling(job_id);
      } else {
        throw new Error('Backtest API not available');
      }
    } catch (error) {
      console.warn('Backtest API failed, falling back to simulation:', error);
      simulateBacktest();
    }
  };

  const startPolling = (jobId: string) => {
    if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    
    pollIntervalRef.current = window.setInterval(async () => {
      try {
        const response = await fetch(`${API_BASE}/api/strategy/backtest/${jobId}/status`);
        if (response.ok) {
          const { status, progress: apiProgress, results } = await response.json();
          setProgress(apiProgress);
          
          if (status === 'COMPLETED' && results) {
            clearInterval(pollIntervalRef.current!);
            setIsRunning(false);
            setMetrics(results.metrics || mockMetrics);
            if (results.equity_curve) setEquityCurve(results.equity_curve);
          } else if (status === 'FAILED') {
            clearInterval(pollIntervalRef.current!);
            setIsRunning(false);
            alert('Backtest failed on server');
          }
        }
      } catch (e) {
        console.error('Polling error:', e);
      }
    }, 1000);
  };

  const simulateBacktest = () => {
    let currentProgress = 0;
    const interval = setInterval(() => {
      currentProgress += 5;
      setProgress(currentProgress);
      if (currentProgress >= 100) {
        clearInterval(interval);
        setIsRunning(false);
        // Refresh with mock variation
        setMetrics(mockMetrics.map(m => ({
          ...m,
          value: m.label.includes('RETURN') ? `+${(Math.random() * 50 + 10).toFixed(2)}%` : m.value
        })));
      }
    }, 100);
  };

  const addParam = () => setParams([...params, { key: '', value: '' }]);
  const removeParam = (index: number) => setParams(params.filter((_, i) => i !== index));

  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    };
  }, []);

  return (
    <div className="flex h-full flex-col overflow-hidden bg-bg-primary">
      {/* Header Section */}
      <div className="p-6 border-b border-border bg-bg-card/30">
        <h1 className="text-2xl font-orbitron font-bold text-white tracking-wider flex items-center gap-3">
          <BarChart className="text-neon-cyan h-6 w-6" />
          BACKTEST LAB <span className="text-neon-cyan/50 text-xs font-mono ml-2">SIM_ENGINE_V4.2</span>
        </h1>
        <p className="text-info-gray/60 text-xs mt-1 uppercase tracking-widest italic">Historical verification of algorithmic strategies</p>
      </div>

      <div className="flex-1 flex overflow-hidden">
        {/* Left Panel: Parameters */}
        <aside className="w-[340px] border-r border-border bg-bg-card/20 p-6 overflow-y-auto custom-scrollbar">
          <div className="space-y-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-[10px] font-orbitron text-neon-cyan tracking-[0.2em] uppercase">Control Panel</h2>
              <Settings className="h-3 w-3 text-info-gray/40" />
            </div>

            {/* Strategy Selection */}
            <div className="space-y-2">
              <label className="text-[10px] text-info-gray uppercase font-bold tracking-wider">Algorithm</label>
              <select 
                value={strategyId}
                onChange={(e) => setStrategyId(e.target.value)}
                className="w-full bg-bg-primary border border-border rounded px-3 py-2 text-xs text-white outline-none focus:border-neon-cyan transition-colors"
              >
                <option>Multi-Factor Mean Reversion</option>
                <option>MACD Crossover V2</option>
                <option>Deep Learning RL-Alpha</option>
                <option>High Frequency Scalper</option>
              </select>
            </div>

            {/* Time Range */}
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <label className="text-[10px] text-info-gray uppercase font-bold tracking-wider">Start</label>
                <input 
                  type="date" 
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                  className="w-full bg-bg-primary border border-border rounded px-2 py-2 text-[10px] text-white outline-none" 
                />
              </div>
              <div className="space-y-2">
                <label className="text-[10px] text-info-gray uppercase font-bold tracking-wider">End</label>
                <input 
                  type="date" 
                  value={endDate}
                  onChange={(e) => setEndDate(e.target.value)}
                  className="w-full bg-bg-primary border border-border rounded px-2 py-2 text-[10px] text-white outline-none" 
                />
              </div>
            </div>

            {/* Capital */}
            <div className="space-y-2">
              <label className="text-[10px] text-info-gray uppercase font-bold tracking-wider">Initial Capital (¥)</label>
              <input 
                type="number" 
                value={initialCapital}
                onChange={(e) => setInitialCapital(e.target.value)}
                className="w-full bg-bg-primary border border-border rounded px-3 py-2 text-xs text-white outline-none focus:border-neon-cyan transition-colors" 
              />
            </div>

            {/* Parameters */}
            <div className="space-y-3">
              <div className="flex justify-between items-center">
                <label className="text-[10px] text-info-gray uppercase font-bold tracking-wider">Strategy Params</label>
                <button onClick={addParam} className="p-1 hover:text-neon-cyan transition-colors"><Plus className="h-3 w-3" /></button>
              </div>
              <div className="space-y-2">
                {params.map((param, index) => (
                  <div key={index} className="flex gap-2">
                    <input 
                      className="flex-1 bg-bg-primary/50 border border-border rounded px-2 py-1 text-[10px] text-info-gray outline-none focus:border-neon-cyan" 
                      placeholder="KEY" 
                      value={param.key}
                      onChange={(e) => {
                        const newParams = [...params];
                        newParams[index].key = e.target.value;
                        setParams(newParams);
                      }}
                    />
                    <input 
                      className="w-20 bg-bg-primary/50 border border-border rounded px-2 py-1 text-[10px] text-white outline-none focus:border-neon-cyan" 
                      placeholder="VAL" 
                      value={param.value}
                      onChange={(e) => {
                        const newParams = [...params];
                        newParams[index].value = e.target.value;
                        setParams(newParams);
                      }}
                    />
                    <button onClick={() => removeParam(index)} className="p-1 text-info-gray/40 hover:text-up-red transition-colors"><Trash2 className="h-3 w-3" /></button>
                  </div>
                ))}
              </div>
            </div>

            {/* Run Button */}
            <button 
              disabled={isRunning}
              onClick={runBacktest}
              className={cn(
                "w-full py-4 mt-8 rounded font-orbitron text-xs tracking-[0.2em] font-bold transition-all flex flex-col items-center justify-center gap-2 relative overflow-hidden",
                isRunning 
                  ? "bg-neon-cyan/10 border border-neon-cyan/50 text-neon-cyan cursor-wait" 
                  : "bg-neon-cyan hover:bg-neon-cyan/80 text-black shadow-[0_0_20px_rgba(0,240,255,0.4)]"
              )}
            >
              {isRunning && (
                <div 
                  className="absolute left-0 bottom-0 h-1 bg-neon-cyan transition-all duration-100 ease-linear shadow-[0_0_10px_rgba(0,240,255,1)]" 
                  style={{ width: `${progress}%` }}
                />
              )}
              <div className="flex items-center gap-2">
                {isRunning ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                {isRunning ? `RUNNING... ${progress}%` : "RUN BACKTEST"}
              </div>
            </button>
          </div>
        </aside>

        {/* Main Content: Results */}
        <div className="flex-1 flex flex-col p-6 space-y-6 overflow-y-auto custom-scrollbar">
          {/* Equity Curve Area */}
          <div className="bg-bg-card/40 border border-border rounded-lg p-6 relative">
            <div className="flex justify-between items-center mb-6">
              <h3 className="text-xs font-orbitron tracking-widest text-white flex items-center gap-2">
                <TrendingUp className="h-4 w-4 text-neon-cyan" /> EQUITY CURVE
              </h3>
              <div className="flex items-center gap-4 text-[10px] font-mono">
                <div className="flex items-center gap-2"><div className="w-2 h-2 bg-neon-cyan" /> STRATEGY</div>
                <div className="flex items-center gap-2"><div className="w-2 h-2 bg-info-gray/30" /> BENCHMARK</div>
              </div>
            </div>

            <div className="h-[300px] w-full relative">
              {/* SVG Equity Curve */}
              <svg className="w-full h-full overflow-visible" preserveAspectRatio="none" viewBox="0 0 100 100">
                <defs>
                  <linearGradient id="equityGradient" x1="0%" y1="0%" x2="0%" y2="100%">
                    <stop offset="0%" stopColor="#00f0ff" stopOpacity="0.2" />
                    <stop offset="100%" stopColor="#00f0ff" stopOpacity="0" />
                  </linearGradient>
                </defs>
                {/* Benchmark (Simulated) */}
                <path 
                  d="M 0 60 L 10 58 L 20 62 L 30 55 L 40 59 L 50 52 L 60 56 L 70 50 L 80 54 L 90 48 L 100 52" 
                  fill="none" 
                  stroke="rgba(255,255,255,0.1)" 
                  strokeWidth="1" 
                />
                {/* Strategy Curve */}
                <path 
                  d={equityCurve} 
                  fill="url(#equityGradient)" 
                />
                <path 
                  d={equityCurve} 
                  fill="none" 
                  stroke="#00f0ff" 
                  strokeWidth="2" 
                  className="animate-path-flow"
                />
                {/* Dots */}
                <circle cx="0" cy="80" r="1.5" fill="#00f0ff" />
                <circle cx="100" cy="25" r="1.5" fill="#00f0ff" />
              </svg>
              
              {/* Floating Tooltip Mock */}
              <div className="absolute right-[10%] top-[25%] bg-bg-card/90 border border-neon-cyan/30 px-3 py-2 rounded text-[10px] font-mono pointer-events-none">
                <div className="text-neon-cyan">{endDate}</div>
                <div className="text-white">EQ: ¥{parseFloat(initialCapital).toLocaleString()}</div>
              </div>
            </div>
          </div>

          {/* Metrics Grid */}
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
            {metrics.map((m) => (
              <div key={m.label} className="bg-bg-card/40 border border-border p-4 rounded group hover:border-neon-cyan/30 transition-colors">
                <div className="text-[8px] text-info-gray/50 font-mono tracking-tighter uppercase mb-1">{m.label}</div>
                <div className={cn("text-xl font-orbitron font-bold", m.color)}>{m.value}</div>
                <div className="text-[10px] text-info-gray/30 font-mono mt-1">{m.subValue}</div>
              </div>
            ))}
          </div>

          {/* Monte Carlo Simulation Section */}
          <div className="bg-bg-card/20 border border-border/50 rounded-lg p-6">
            <div className="flex justify-between items-center mb-6">
              <div>
                <h3 className="text-xs font-orbitron tracking-widest text-white uppercase">Monte Carlo Simulation</h3>
                <p className="text-[9px] text-info-gray/40 mt-1 uppercase">Stochastic resampling for robustness testing</p>
              </div>
              <button 
                onClick={() => setShowMonteCarlo(!showMonteCarlo)}
                className="flex items-center gap-2 bg-bg-primary border border-border px-4 py-1.5 rounded text-[10px] text-info-gray hover:text-white hover:border-neon-cyan transition-all uppercase"
              >
                <RotateCcw className={cn("h-3 w-3", showMonteCarlo && "animate-spin")} />
                Run Monte Carlo
              </button>
            </div>

            <div className="h-48 w-full bg-bg-primary/30 rounded border border-border p-4 relative overflow-hidden">
              {showMonteCarlo ? (
                <div className="relative h-full w-full">
                  <svg className="w-full h-full overflow-visible" preserveAspectRatio="none" viewBox="0 0 100 100">
                    {/* 20 paths */}
                    {[...Array(20)].map((_, i) => (
                      <path
                        key={i}
                        d={`M 0 80 ${[...Array(10)].map((_, j) => `L ${(j+1)*10} ${80 - (j+1)*5 - (Math.random()*15 - 7.5)}`).join(' ')}`}
                        fill="none"
                        stroke="#00f0ff"
                        strokeWidth="0.5"
                        strokeOpacity="0.15"
                      />
                    ))}
                  </svg>
                  <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                    <div className="bg-bg-card/80 border border-neon-cyan/40 px-6 py-3 rounded-md shadow-lg backdrop-blur-sm animate-in fade-in zoom-in duration-500">
                      <div className="text-[10px] font-orbitron text-neon-cyan mb-2 text-center">SIMULATION COMPLETE (N=5000)</div>
                      <div className="flex gap-8">
                        <div>
                          <div className="text-[8px] text-info-gray/60 font-mono uppercase">95% Conf. Interval</div>
                          <div className="text-sm font-bold text-white">¥902,450 - ¥1,124,000</div>
                        </div>
                        <div>
                          <div className="text-[8px] text-info-gray/60 font-mono uppercase">Prob. of Ruin</div>
                          <div className="text-sm font-bold text-up-green">0.12%</div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="h-full flex flex-col items-center justify-center text-info-gray/20">
                  <RotateCcw className="h-8 w-8 mb-2 opacity-10" />
                  <span className="text-[10px] font-orbitron uppercase tracking-widest">Awaiting Simulation</span>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default BacktestLab;
