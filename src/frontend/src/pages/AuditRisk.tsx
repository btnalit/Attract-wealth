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
import { monitorApi } from '../services/api';

// --- Types ---
interface RiskGaugeData { label: string; current: number | null; threshold: number | null; color: string; unit: string; decimals?: number }
interface AuditLog { id: string; time: string; type: string; severity: string; description: string; payload: any }
interface RiskSwitch { id: string; label: string; description: string; enabled: boolean }

// --- SEVERITY CONFIG ---
const SEVERITY_COLOR: Record<string, { text: string; glow: string }> = {
  'Low': { text: 'text-white/70', glow: 'shadow-[0_0_8px_rgba(255,255,255,0.2)] border-white/20' },
  'Medium': { text: 'text-warn-gold', glow: 'shadow-[0_0_10px_rgba(255,215,0,0.3)] border-warn-gold/30' },
  'High': { text: 'text-down-red', glow: 'shadow-[0_0_12px_rgba(255,0,85,0.4)] border-down-red/40' },
};

const SWITCH_META: Record<string, { label: string; description: string }> = {
  auto_stop: {
    label: 'Auto Stop-Loss',
    description: 'Emergency sell if loss > 5% on single position',
  },
  blacklist: {
    label: 'Blacklist Filter',
    description: 'Prevent trading restricted securities',
  },
  deviation: {
    label: 'Price Deviation Check',
    description: 'Block orders deviating > 2% from market price',
  },
  global_pause: {
    label: 'Global Pause',
    description: 'Pause all trading actions immediately',
  },
  trading_pause: {
    label: 'Trading Pause',
    description: 'Pause order submission while keeping monitoring active',
  },
  daily_reset: {
    label: 'Daily Reset',
    description: 'Manual daily counters reset for risk gate',
  },
};

const SWITCH_ORDER = ['auto_stop', 'blacklist', 'deviation', 'global_pause', 'trading_pause', 'daily_reset'];

const parsePayloadData = <T,>(payload: unknown): T => {
  if (payload && typeof payload === 'object' && 'data' in payload) {
    return (payload as { data: T }).data;
  }
  return payload as T;
};

const toOptionalNumber = (value: unknown): number | null => {
  if (value === null || value === undefined) {
    return null;
  }
  if (typeof value === 'string' && value.trim() === '') {
    return null;
  }
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
};

const toPercent = (value: unknown): number | null => {
  const num = toOptionalNumber(value);
  return num === null ? null : Number((num * 100).toFixed(2));
};

const toEpochMs = (value: unknown): number | null => {
  const ts = toOptionalNumber(value);
  if (ts === null || ts <= 0) {
    return null;
  }
  return ts > 1_000_000_000_000 ? ts : ts * 1000;
};

const formatAuditTime = (value: unknown): string => {
  const ts = toEpochMs(value);
  return ts === null ? '--' : new Date(ts).toLocaleTimeString();
};

const formatGaugeValue = (value: number | null, decimals = 0): string => {
  if (value === null) {
    return '--';
  }
  return value.toFixed(decimals);
};

const toSwitches = (payload: unknown): RiskSwitch[] => {
  if (!payload || typeof payload !== 'object') {
    return [];
  }

  const source = payload as Record<string, unknown>;
  const orderedIds = [
    ...SWITCH_ORDER.filter((id) => id in source),
    ...Object.keys(source).filter((id) => !SWITCH_ORDER.includes(id)),
  ];

  return orderedIds.map((id) => ({
    id,
    label: SWITCH_META[id]?.label || id,
    description: SWITCH_META[id]?.description || 'Runtime risk switch',
    enabled: Boolean(source[id]),
  }));
};

// --- HELPER COMPONENT: GAUGE ---
const RiskGauge: FC<{ gauge: RiskGaugeData }> = ({ gauge }) => {
  const hasCurrent = gauge.current !== null;
  const hasThreshold = gauge.threshold !== null;
  const hasData = hasCurrent && hasThreshold;
  const percentage = hasData && Number(gauge.threshold) > 0
    ? Math.min((Number(gauge.current) / Number(gauge.threshold)) * 100, 100)
    : 0;
  const strokeDasharray = 283; // 2 * PI * 45
  const strokeDashoffset = strokeDasharray - (percentage / 100) * strokeDasharray;
  const decimals = gauge.decimals ?? 0;
  const gaugeColor = hasData ? gauge.color : 'text-info-gray/40';

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
            className={cn(gaugeColor, "transition-all duration-1000 ease-out")}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className={cn('text-2xl font-orbitron font-bold leading-none', hasData ? 'text-white' : 'text-info-gray/70')}>
            {formatGaugeValue(gauge.current, decimals)}
          </span>
          <span className="text-[10px] text-info-gray/60 mt-1 uppercase tracking-tighter">
            阈值: {formatGaugeValue(gauge.threshold, decimals)}{gauge.unit}
          </span>
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
  const [errorMessage, setErrorMessage] = useState('');
  const [actionMessage, setActionMessage] = useState('');
  const [emergencyLocking, setEmergencyLocking] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setErrorMessage('');
    try {
      const [riskPayload, auditPayload] = await Promise.all([
        monitorApi.getRisk<Record<string, unknown>>(),
        monitorApi.getAuditLogs<Array<Record<string, unknown>>>(20),
      ]);
      const d = parsePayloadData<Record<string, unknown>>(riskPayload) || {};
      setGauges([
        { label: '最大回撤', current: toPercent(d.max_drawdown_current), threshold: toPercent(d.max_drawdown_threshold), color: 'text-up-green', unit: '%', decimals: 2 },
        { label: '单仓限制', current: toPercent(d.position_limit_current), threshold: toPercent(d.position_limit_threshold), color: 'text-neon-cyan', unit: '%', decimals: 2 },
        { label: '每日交易频次', current: toOptionalNumber(d.trade_frequency_day), threshold: 500, color: 'text-warn-gold', unit: 'req', decimals: 0 },
        { label: 'API 速率限制', current: toOptionalNumber(d.api_rate_limit_percent), threshold: 100, color: 'text-neon-magenta', unit: '%', decimals: 2 },
      ]);
      setSwitches(toSwitches(d.switches));

      const raw = parsePayloadData<Array<Record<string, unknown>>>(auditPayload);
      const safeRaw = Array.isArray(raw) ? raw : [];
      setAuditLogs(safeRaw.map((l: any, i: number) => ({
        id: `LOG_${i}`,
        time: formatAuditTime(l.timestamp),
        type: String(l.type ?? ''),
        severity: String(l.severity ?? ''),
        description: String(l.message ?? ''),
        payload: l.payload
      })));

    } catch (err) {
      const errMsg = err instanceof Error ? err.message : '审计与风控数据拉取失败。';
      setErrorMessage(errMsg);
      setGauges([]);
      setAuditLogs([]);
      setSwitches([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const toggleSwitch = async (id: string) => {
    const s = switches.find(x => x.id === id);
    if (!s) return;

    setErrorMessage('');
    setActionMessage('');
    try {
      const payload = await monitorApi.toggleRiskSwitch<Record<string, unknown>>({ name: id, enabled: !s.enabled });
      const parsed = parsePayloadData<Record<string, unknown>>(payload) || {};
      const serverSwitches = parsed.switches;
      if (serverSwitches && typeof serverSwitches === 'object') {
        setSwitches(toSwitches(serverSwitches));
      } else {
        setSwitches(prev => prev.map(item => item.id === id ? { ...item, enabled: !item.enabled } : item));
      }
      setActionMessage(`${s.label} 已${s.enabled ? '关闭' : '开启'}。`);
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : '风控开关切换失败。';
      setErrorMessage(errMsg);
    }
  };

  const forceEmergencyLock = async () => {
    setEmergencyLocking(true);
    setErrorMessage('');
    setActionMessage('');
    try {
      const payload = await monitorApi.toggleRiskSwitch<Record<string, unknown>>({
        name: 'global_pause',
        enabled: true,
      });
      const parsed = parsePayloadData<Record<string, unknown>>(payload) || {};
      const serverSwitches = parsed.switches;
      if (serverSwitches && typeof serverSwitches === 'object') {
        setSwitches(toSwitches(serverSwitches));
      }
      setActionMessage('已触发全局暂停（Global Pause）。');
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : '触发紧急锁定失败。';
      setErrorMessage(errMsg);
    } finally {
      setEmergencyLocking(false);
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
      {errorMessage && (
        <div className="text-xs text-down-red bg-down-red/10 border border-down-red/40 rounded-sm px-3 py-2">
          {errorMessage}
        </div>
      )}
      {actionMessage && (
        <div className="text-xs text-up-green bg-up-green/10 border border-up-green/40 rounded-sm px-3 py-2">
          {actionMessage}
        </div>
      )}

      {/* Risk Limit Dashboard */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {gauges.length > 0 ? gauges.map((g, i) => (
          <RiskGauge key={i} gauge={g} />
        )) : loading ? Array(4).fill(0).map((_, i) => (
          <div key={i} className="h-48 bg-bg-card/50 border border-border animate-pulse rounded-sm" />
        )) : (
          <div className="col-span-2 lg:col-span-4 h-24 rounded-sm border border-dashed border-border flex items-center justify-center text-xs text-info-gray/60">
            当前暂无可展示的风控指标。
          </div>
        )}
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
                {auditLogs.length > 0 ? auditLogs.map(log => (
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
                )) : (
                  <tr>
                    <td colSpan={4} className="px-4 py-6 text-center text-info-gray/60">
                      暂无审计日志
                    </td>
                  </tr>
                )}
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
            {switches.length > 0 ? switches.map((s) => (
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
            )) : (
              <div className="text-xs text-info-gray/60 px-1">
                暂无可切换的风控开关。
              </div>
            )}
          </div>

          <div className="mt-auto p-4 bg-bg-primary/30 border-t border-border">
            <button
              onClick={() => void forceEmergencyLock()}
              disabled={emergencyLocking}
              className="w-full flex items-center justify-center gap-2 py-2 bg-down-red/10 border border-down-red/50 text-down-red text-xs font-bold uppercase rounded-sm hover:bg-down-red/20 transition-all disabled:opacity-60"
            >
              {emergencyLocking ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldX className="h-4 w-4" />}
              {emergencyLocking ? '锁定中...' : '强制紧急锁定'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default AuditRisk;
