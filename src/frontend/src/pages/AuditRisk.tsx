import { useState, useEffect, useCallback, FC, Fragment } from 'react';
import { 
  ShieldCheck, 
  ShieldAlert, 
  ShieldX, 
  Lock, 
  AlertTriangle, 
  ShieldQuestion, 
  Loader2,
  RefreshCw
} from 'lucide-react';
import { cn } from '../lib/utils';
import { PageTitle } from '../components/PageTitle';
import { Button } from '../components/ui/button';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

// --- Types ---
interface RiskGaugeData { label: string; current: number; threshold: number; color: string; unit: string }
interface AuditLog { id: string; time: string; type: string; severity: string; description: string; payload: any }
interface RiskSwitch { id: string; label: string; description: string; enabled: boolean }

// --- SEVERITY CONFIG ---
const SEVERITY_COLOR: Record<string, { text: string; glow: string }> = {
  'Low': { text: 'text-white/70', glow: 'shadow-[0_0_8px_rgba(255,255,255,0.2)] border-white/20' },
  'Medium': { text: 'text-warn-gold', glow: 'shadow-[0_0_10px_rgba(255,215,0,0.3)] border-warn-gold/30' },
  'High': { text: 'text-down-red', glow: 'shadow-[0_0_12px_rgba(255,0,85,0.4)] border-down-red/40' },
};

// --- HELPER COMPONENT: GAUGE ---
const RiskGauge: FC<{ gauge: RiskGaugeData }> = ({ gauge }) => {
  const percentage = Math.min((gauge.current / gauge.threshold) * 100, 100);
  const strokeDasharray = 283; // 2 * PI * 45
  const strokeDashoffset = strokeDasharray - (percentage / 100) * strokeDasharray;

  return (
    <div className="bg-bg-card border border-border rounded-sm p-5 flex flex-col items-center group hover:border-neon-cyan/50 transition-all">
      <div className="relative w-32 h-32 mb-4">
        <svg className="w-full h-full -rotate-90">
          <circle 
            cx="64" cy="64" r="45" 
            fill="none" 
            stroke="currentColor" 
            strokeWidth="8"
            className="text-border/30"
          />
          <circle 
            cx="64" cy="64" r="45" 
            fill="none" 
            stroke="currentColor" 
            strokeWidth="8"
            strokeDasharray={strokeDasharray}
            strokeDashoffset={strokeDashoffset}
            strokeLinecap="round"
            className={cn(gauge.color, "transition-all duration-1000 ease-out")}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-2xl font-orbitron font-bold text-white leading-none">{gauge.current}</span>
          <span className="text-[10px] text-info-gray/60 mt-1 uppercase tracking-tighter">阈值: {gauge.threshold}{gauge.unit}</span>
        </div>
      </div>
      <h3 className="font-orbitron text-xs font-bold text-info-gray uppercase tracking-widest group-hover:text-neon-cyan transition-colors">
        {gauge.label}
      </h3>
    </div>
  );
};

export const AuditRisk: FC = () => {
  const [gauges, setGauges] = useState<RiskGaugeData[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditLog[]>([]);
  const [switches, setSwitches] = useState<RiskSwitch[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedLog, setExpandedLog] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [riskRes, auditRes] = await Promise.all([
        fetch(`${API_BASE}/api/v1/monitor/risk`),
        fetch(`${API_BASE}/api/v1/monitor/audit?limit=20`),
      ]);

      if (riskRes.ok) {
        const json = await riskRes.json();
        const d = json.data || {};
        setGauges([
          { label: '最大回撤', current: (d.max_drawdown_current || 0.024) * 100, threshold: (d.max_drawdown_threshold || 0.10) * 100, color: 'text-up-green', unit: '%' },
          { label: '单仓限制', current: (d.position_limit_current || 0.15) * 100, threshold: (d.position_limit_threshold || 0.30) * 100, color: 'text-neon-cyan', unit: '%' },
          { label: '每日交易频次', current: d.trade_frequency_day || 12, threshold: 500, color: 'text-warn-gold', unit: 'req' },
          { label: 'API 速率限制', current: d.api_rate_limit_percent || 42.0, threshold: 100, color: 'text-neon-magenta', unit: '%' },
        ]);
      }

      if (auditRes.ok) {
        const json = await auditRes.json();
        const raw = json.data || [];
        setAuditLogs(raw.map((l: any, i: number) => ({
          id: `LOG_${i}`,
          time: new Date(l.timestamp * 1000).toLocaleTimeString(),
          type: l.type,
          severity: l.severity,
          description: l.message,
          payload: l.payload
        })));
      }

      // Initial switches
      setSwitches([
        { id: 'auto_stop', label: 'Auto Stop-Loss', description: 'Emergency sell if loss > 5% on single position', enabled: true },
        { id: 'blacklist', label: 'Blacklist Filter', description: 'Prevent trading restricted securities', enabled: true },
        { id: 'deviation', label: 'Price Deviation Check', description: 'Block orders deviating > 2% from market price', enabled: false },
      ]);

    } catch (err) {
      console.warn('[AuditRisk] API fetch failed:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const toggleSwitch = async (id: string) => {
    const s = switches.find(x => x.id === id);
    if (!s) return;
    
    try {
      const res = await fetch(`${API_BASE}/api/v1/monitor/risk/toggle`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: id, enabled: !s.enabled })
      });
      if (res.ok) {
        setSwitches(prev => prev.map(item => item.id === id ? { ...item, enabled: !item.enabled } : item));
      }
    } catch (err) {
      console.error('Failed to toggle switch:', err);
    }
  };

  return (
    <div className="p-6 space-y-6">
      <div className="flex justify-between items-center">
        <PageTitle 
          title="审计与风控" 
          subtitle="安全校验、合规监控与风险阈值管理" 
        />
        <Button variant="outline" size="sm" className="gap-2" onClick={fetchData}>
          <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
          <span>刷新</span>
        </Button>
      </div>

      {/* Risk Limit Dashboard */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {gauges.length > 0 ? gauges.map((g, i) => (
          <RiskGauge key={i} gauge={g} />
        )) : Array(4).fill(0).map((_, i) => (
          <div key={i} className="h-48 bg-bg-card/50 border border-border animate-pulse rounded-sm" />
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-start">
        {/* Compliance Audit Logs */}
        <div className="lg:col-span-2 flex flex-col bg-bg-card border border-border rounded-sm overflow-hidden min-h-[400px]">
          <div className="flex justify-between items-center px-4 py-3 border-b border-border bg-bg-card/50">
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-4 w-4 text-neon-cyan" />
              <span className="font-orbitron text-sm font-bold tracking-widest uppercase text-white">安全审计日志</span>
            </div>
            {loading && <Loader2 className="h-4 w-4 animate-spin text-info-gray" />}
          </div>
          
          <div className="flex-1 overflow-auto custom-scrollbar">
            <table className="w-full text-left text-xs">
              <thead className="sticky top-0 bg-bg-card border-b border-border z-10">
                <tr className="text-info-gray uppercase font-mono tracking-tighter">
                  <th className="px-4 py-3">时间戳</th>
                  <th className="px-4 py-3">类型</th>
                  <th className="px-4 py-3">严重程度</th>
                  <th className="px-4 py-3">描述</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/30">
                {auditLogs.map(log => (
                  <Fragment key={log.id}>
                    <tr 
                      className={cn(
                        "hover:bg-bg-hover transition-colors cursor-pointer group",
                        expandedLog === log.id && "bg-bg-hover/50"
                      )}
                      onClick={() => setExpandedLog(expandedLog === log.id ? null : log.id)}
                    >
                      <td className="px-4 py-3 font-mono text-info-gray/60">{log.time}</td>
                      <td className="px-4 py-3">
                        <span className="px-1.5 py-0.5 bg-bg-primary border border-border rounded text-[10px] uppercase font-bold text-info-gray">
                          {log.type}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div className={cn(
                          "px-2 py-0.5 rounded-sm text-[10px] font-bold border inline-flex items-center gap-1 uppercase",
                          SEVERITY_COLOR[log.severity]?.text || 'text-white',
                          SEVERITY_COLOR[log.severity]?.glow || ''
                        )}>
                          {log.severity === 'High' && <ShieldAlert className="h-2.5 w-2.5" />}
                          {log.severity === 'Medium' && <AlertTriangle className="h-2.5 w-2.5" />}
                          {log.severity === 'Low' && <ShieldQuestion className="h-2.5 w-2.5" />}
                          {log.severity}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-info-gray group-hover:text-white transition-colors">
                        {log.description}
                      </td>
                    </tr>
                    {expandedLog === log.id && (
                      <tr className="bg-bg-primary/50">
                        <td colSpan={4} className="px-4 py-4">
                          <div className="bg-black/40 border border-border p-3 rounded-sm font-mono text-[10px] text-up-green/80">
                            <pre>{JSON.stringify(log.payload, null, 2)}</pre>
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Risk Control Matrix */}
        <div className="flex flex-col bg-bg-card border border-border rounded-sm overflow-hidden">
          <div className="px-4 py-3 border-b border-border bg-bg-card/50 flex items-center gap-2">
            <Lock className="h-4 w-4 text-warn-gold" />
            <span className="font-orbitron text-sm font-bold tracking-widest uppercase text-white">风控矩阵</span>
          </div>
          
          <div className="p-4 space-y-4">
            {switches.map((s) => (
              <div key={s.id} className="flex flex-col gap-2 p-3 bg-bg-primary/50 border border-border/50 rounded hover:border-neon-cyan/30 transition-all group">
                <div className="flex justify-between items-center">
                  <span className="text-white font-bold text-xs uppercase tracking-wider">{s.label}</span>
                  <button 
                    onClick={() => toggleSwitch(s.id)}
                    className={cn(
                      "relative w-10 h-5 rounded-full transition-all duration-300",
                      s.enabled ? "bg-up-green/20" : "bg-down-red/20"
                    )}
                  >
                    <div className={cn(
                      "absolute top-1 w-3 h-3 rounded-full transition-all duration-300",
                      s.enabled ? "right-1 bg-up-green shadow-[0_0_8px_rgba(0,255,157,0.8)]" : "left-1 bg-down-red shadow-[0_0_8px_rgba(255,0,85,0.8)]"
                    )} />
                  </button>
                </div>
                <p className="text-[10px] text-info-gray/60 leading-relaxed italic">
                  {s.description}
                </p>
              </div>
            ))}
          </div>

          <div className="mt-auto p-4 bg-bg-primary/30 border-t border-border">
            <button className="w-full flex items-center justify-center gap-2 py-2 bg-down-red/10 border border-down-red/50 text-down-red text-xs font-bold uppercase rounded-sm hover:bg-down-red/20 transition-all">
              <ShieldX className="h-4 w-4" />
              强制紧急锁定
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default AuditRisk;
