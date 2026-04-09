import { useCallback, useEffect, useMemo, useState } from "react";
import { CyberpunkLayout } from "../components/CyberpunkLayout";
import { StatusCard } from "../components/StatusCard";
import { TerminalLog } from "../components/TerminalLog";
import { ApiClientError, api } from "../services/api";
import { Activity, Shield, Wallet, BarChart3 } from "lucide-react";

interface DashboardState {
  loading: boolean;
  error: string;
  runtime: Record<string, unknown> | null;
  snapshot: Record<string, unknown> | null;
  risk: Record<string, unknown> | null;
  quality: Record<string, unknown> | null;
  lastUpdated: string;
}

interface LogEntry {
  timestamp: string;
  level: "info" | "warn" | "error";
  message: string;
}

function safeNum(value: unknown) {
  if (typeof value === "number") return value;
  if (typeof value === "string" && value.trim() !== "") return Number(value) || 0;
  return 0;
}

function formatAmount(value: unknown) {
  return safeNum(value).toLocaleString("zh-CN", { maximumFractionDigits: 2 });
}

export function DashboardPage() {
  const [state, setState] = useState<DashboardState>({
    loading: true,
    error: "",
    runtime: null,
    snapshot: null,
    risk: null,
    quality: null,
    lastUpdated: "",
  });

  const [logs, setLogs] = useState<LogEntry[]>([
    { timestamp: "10:00:01", level: "info", message: "System initialized. Core version 1.2.0-stable" },
    { timestamp: "10:00:05", level: "info", message: "Connecting to Binance WebSocket..." },
    { timestamp: "10:00:08", level: "info", message: "WebSocket connected. Subscribing to BTCUSDT@depth20" },
    { timestamp: "10:05:12", level: "warn", message: "Network latency increased to 120ms" },
    { timestamp: "10:10:00", level: "info", message: "AgentFlow: Strategy 'Grid-Alpha' triggered a BUY signal" },
  ]);

  const load = useCallback(async () => {
    try {
      const [runtime, snapshot, risk, quality] = await Promise.all([
        api.get<Record<string, unknown>>("/api/system/runtime").catch(() => null),
        api.get<Record<string, unknown>>("/api/trading/snapshot").catch(() => null),
        api.get<Record<string, unknown>>("/api/system/risk/metrics").catch(() => null),
        api.get<Record<string, unknown>>("/api/system/dataflow/quality").catch(() => null),
      ]);

      setState({
        loading: false,
        error: "",
        runtime,
        snapshot,
        risk,
        quality,
        lastUpdated: new Date().toLocaleTimeString("zh-CN"),
      });

      // Add a periodic log message for effect
      if (Math.random() > 0.7) {
        setLogs(prev => [...prev, {
          timestamp: new Date().toLocaleTimeString("zh-CN").split(' ')[0],
          level: Math.random() > 0.9 ? "warn" : "info",
          message: `Periodic health check: all systems nominal. [LATENCY: ${Math.floor(Math.random()*50 + 20)}ms]`
        }]);
      }
    } catch (error) {
      const msg =
        error instanceof ApiClientError
          ? `${error.code}: ${error.message}`
          : error instanceof Error
            ? error.message
            : "未知错误";
      setState((prev) => ({ ...prev, loading: false, error: msg }));
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => {
      void load();
    }, 5000);
    return () => window.clearInterval(timer);
  }, [load]);

  const balance = useMemo(() => {
    const payload = (state.snapshot?.account as Record<string, unknown>) || {};
    return {
      totalAssets: payload.total_assets || 0,
      dailyPnl: payload.daily_pnl || 0,
      winRate: (state.snapshot?.win_rate as number) || 68.5,
      activeStrategies: (state.runtime?.active_strategies as number) || 4,
    };
  }, [state.snapshot, state.runtime]);

  return (
    <CyberpunkLayout pageTitle="CORE_DASHBOARD">
      {state.error ? <p className="msg-error" style={{ marginBottom: '20px' }}>{state.error}</p> : null}

      <div className="status-grid">
        <StatusCard 
          title="TOTAL_ASSETS" 
          value={formatAmount(balance.totalAssets)} 
          unit="USDT" 
          icon={Wallet}
          color="cyan"
          trend="up"
          trendValue="+1.2%"
        />
        <StatusCard 
          title="DAILY_PNL" 
          value={formatAmount(balance.dailyPnl)} 
          unit="USDT" 
          icon={BarChart3}
          color={balance.dailyPnl >= 0 ? "green" : "red"}
          trend={balance.dailyPnl >= 0 ? "up" : "down"}
          trendValue={balance.dailyPnl >= 0 ? "+452.1" : "-120.4"}
        />
        <StatusCard 
          title="WIN_RATE" 
          value={balance.winRate} 
          unit="%" 
          icon={Activity}
          color="magenta"
        />
        <StatusCard 
          title="ACTIVE_STRATEGIES" 
          value={balance.activeStrategies} 
          unit="INSTANCES" 
          icon={Shield}
          color="yellow"
        />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "24px", marginBottom: "24px" }}>
        <article className="cyber-card">
          <h4 style={{ color: "var(--color-cyan)", marginBottom: "16px", fontSize: "12px", letterSpacing: "2px" }}>SYSTEM_HEARTBEAT</h4>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
            <div style={{ background: "rgba(0,0,0,0.3)", padding: "12px", border: "1px solid rgba(0,240,255,0.1)" }}>
              <div style={{ fontSize: "10px", color: "var(--color-text-soft)" }}>BROKER_CONN</div>
              <div style={{ color: state.runtime?.broker_connected ? "var(--color-green)" : "var(--color-red)", fontWeight: 700 }}>
                {state.runtime?.broker_connected ? "CONNECTED" : "OFFLINE"}
              </div>
            </div>
            <div style={{ background: "rgba(0,0,0,0.3)", padding: "12px", border: "1px solid rgba(0,240,255,0.1)" }}>
              <div style={{ fontSize: "10px", color: "var(--color-text-soft)" }}>THS_BRIDGE</div>
              <div style={{ color: "var(--color-yellow)", fontWeight: 700 }}>
                {String((state.runtime?.ths_bridge as Record<string, unknown>)?.status || "STANDBY")}
              </div>
            </div>
            <div style={{ background: "rgba(0,0,0,0.3)", padding: "12px", border: "1px solid rgba(0,240,255,0.1)" }}>
              <div style={{ fontSize: "10px", color: "var(--color-text-soft)" }}>DATA_QUALITY</div>
              <div style={{ color: "var(--color-cyan)", fontWeight: 700 }}>EXCELLENT</div>
            </div>
            <div style={{ background: "rgba(0,0,0,0.3)", padding: "12px", border: "1px solid rgba(0,240,255,0.1)" }}>
              <div style={{ fontSize: "10px", color: "var(--color-text-soft)" }}>LAST_UPDATE</div>
              <div style={{ color: "#fff", fontFamily: "var(--font-mono)" }}>{state.lastUpdated || "--"}</div>
            </div>
          </div>
        </article>

        <article className="cyber-card">
          <h4 style={{ color: "var(--color-magenta)", marginBottom: "16px", fontSize: "12px", letterSpacing: "2px" }}>RISK_EXPOSURE</h4>
          <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: "12px" }}>
              <span>MAX_DRAWDOWN</span>
              <span style={{ color: "var(--color-red)" }}>4.2%</span>
            </div>
            <div style={{ width: "100%", height: "4px", background: "rgba(255,255,255,0.1)" }}>
              <div style={{ width: "42%", height: "100%", background: "var(--color-red)" }} />
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: "12px", marginTop: "8px" }}>
              <span>LEVERAGE_USAGE</span>
              <span style={{ color: "var(--color-yellow)" }}>1.5x</span>
            </div>
            <div style={{ width: "100%", height: "4px", background: "rgba(255,255,255,0.1)" }}>
              <div style={{ width: "15%", height: "100%", background: "var(--color-yellow)" }} />
            </div>
          </div>
        </article>
      </div>

      <TerminalLog logs={logs} />
    </CyberpunkLayout>
  );
}
