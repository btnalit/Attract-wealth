import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  Clock3,
  Database,
  Loader2,
  RefreshCcw,
  ShieldAlert,
  ShieldCheck,
  TrendingUp,
  Wallet,
  Wifi,
  WifiOff,
  Zap,
} from "lucide-react";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { PageTitle } from "../components/PageTitle";
import { cn } from "../lib/utils";
import { monitorApi, type MonitorOverviewPayload } from "../services/api";

type Severity = "high" | "medium" | "low";

const toOptionalNumber = (value: unknown): number | null => {
  if (value === null || value === undefined) {
    return null;
  }
  if (typeof value === "string" && value.trim() === "") {
    return null;
  }
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
};

const toArray = <T,>(value: unknown): T[] => (Array.isArray(value) ? (value as T[]) : []);

const toTimestamp = (value: unknown): number | null => {
  const num = toOptionalNumber(value);
  if (num === null || num <= 0) {
    return null;
  }
  return num > 1_000_000_000_000 ? num : num * 1000;
};

const fmtMoney = (value: unknown): string => {
  const num = toOptionalNumber(value);
  if (num === null) {
    return "--";
  }
  return `¥${num.toLocaleString("zh-CN", { maximumFractionDigits: 2, minimumFractionDigits: 2 })}`;
};

const fmtPct = (value: unknown): string => {
  const num = toOptionalNumber(value);
  if (num === null) {
    return "--";
  }
  return `${(num * 100).toFixed(2)}%`;
};

const fmtInt = (value: unknown): string => {
  const num = toOptionalNumber(value);
  return num === null ? "--" : `${Math.round(num)}`;
};

const fmtDecimal = (value: unknown, digits: number): string => {
  const num = toOptionalNumber(value);
  return num === null ? "--" : num.toFixed(digits);
};

const fmtClock = (value: unknown): string => {
  const ts = toTimestamp(value);
  if (ts === null) {
    return "--";
  }
  return new Date(ts).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
};

const severityLabel = (value: Severity): string => {
  if (value === "high") {
    return "高";
  }
  if (value === "medium") {
    return "中";
  }
  return "低";
};

const severityVariant = (value: Severity): "destructive" | "warning" | "outline" => {
  if (value === "high") {
    return "destructive";
  }
  if (value === "medium") {
    return "warning";
  }
  return "outline";
};

const readinessVariant = (value: string): "success" | "warning" | "destructive" => {
  if (value === "stable") {
    return "success";
  }
  if (value === "attention") {
    return "warning";
  }
  return "destructive";
};

export const Dashboard: React.FC = () => {
  const [overview, setOverview] = useState<MonitorOverviewPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>("");

  const fetchOverview = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const payload = await monitorApi.getOverview<MonitorOverviewPayload>();
      setOverview(payload);
    } catch (err) {
      setError(String(err));
      setOverview(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchOverview();
  }, [fetchOverview]);

  const wallet = useMemo(() => overview?.wallet ?? {}, [overview]);
  const risk = useMemo(() => overview?.risk ?? {}, [overview]);
  const channels = useMemo(() => toArray<Record<string, unknown>>(overview?.channels), [overview]);
  const positions = useMemo(() => toArray<Record<string, unknown>>(overview?.positions), [overview]);
  const alerts = useMemo(() => toArray<Record<string, unknown>>(overview?.alerts), [overview]);
  const orders = useMemo(() => toArray<Record<string, unknown>>(overview?.recent_orders), [overview]);
  const decision = useMemo(() => (overview?.decision_summary ?? {}) as Record<string, unknown>, [overview]);
  const dataHealth = useMemo(() => (overview?.data_health ?? {}) as Record<string, unknown>, [overview]);
  const recon = useMemo(() => (overview?.reconciliation_guard ?? {}) as Record<string, unknown>, [overview]);

  const readinessScore = toOptionalNumber(overview?.readiness_score);
  const readinessLevelRaw = String(overview?.readiness_level ?? "").trim().toLowerCase();
  const readinessLevel = readinessLevelRaw || "--";
  const onlineChannels = channels.filter((item) => String(item.status ?? "").toLowerCase() === "online").length;
  const drawdownCurrent = toOptionalNumber(risk.max_drawdown_current);
  const drawdownThreshold = toOptionalNumber(risk.max_drawdown_threshold);
  const positionCurrent = toOptionalNumber(risk.position_limit_current);
  const positionThreshold = toOptionalNumber(risk.position_limit_threshold);
  const drawdownRatio =
    drawdownCurrent !== null && drawdownThreshold !== null && drawdownThreshold > 0
      ? drawdownCurrent / drawdownThreshold
      : null;
  const positionRatio =
    positionCurrent !== null && positionThreshold !== null && positionThreshold > 0
      ? positionCurrent / positionThreshold
      : null;
  const riskPressure =
    drawdownRatio === null && positionRatio === null
      ? null
      : Math.min(Math.max(Math.max(drawdownRatio ?? 0, positionRatio ?? 0), 0), 1);
  const generatedAt = fmtClock(overview?.generated_at);

  const pnl = toOptionalNumber(wallet.daily_pnl);
  const pnlIsUp = pnl !== null && pnl >= 0;
  const decisionCount = toOptionalNumber(decision.count);
  const successRatePct = toOptionalNumber(dataHealth.success_rate_pct);
  const avgLatencyMs = toOptionalNumber(dataHealth.avg_latency_ms);

  return (
    <div className="flex h-full flex-col gap-4 p-4 md:p-6">
      <PageTitle
        title="交易作战驾驶舱"
        subtitle="Monitor Overview / API + Service + DAO 聚合链路"
        actions={
          <Button
            variant="outline"
            size="sm"
            onClick={() => void fetchOverview()}
            disabled={loading}
            className="h-8 gap-2"
          >
            <RefreshCcw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
            刷新总览
          </Button>
        }
      />

      {error && (
        <Card className="border-down-red/50">
          <CardContent className="p-4 pt-4">
            <div className="flex items-center gap-2 text-down-red text-xs">
              <AlertTriangle className="h-4 w-4" />
              监控总览拉取失败：{error}
            </div>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 xl:grid-cols-[2fr_1fr]">
        <Card className="border-neon-cyan/40 bg-[radial-gradient(circle_at_top_left,rgba(0,240,255,0.18),transparent_45%),rgba(22,24,28,0.85)]">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-white">
              <Zap className="h-4 w-4 text-neon-cyan" />
              作战态势评分
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-4">
            <div className="flex flex-wrap items-end justify-between gap-4">
              <div>
                <div className="font-orbitron text-4xl font-extrabold text-white">
                  {readinessScore === null ? "--" : readinessScore.toFixed(1)}
                </div>
                <div className="mt-2 flex items-center gap-2">
                  <Badge variant={readinessVariant(readinessLevelRaw || "critical")}>{readinessLevel}</Badge>
                  <span className="text-[10px] uppercase tracking-widest text-info-gray/60">更新时间 {generatedAt}</span>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2 text-xs font-mono">
                <div className="rounded border border-border bg-bg-primary/50 px-3 py-2">
                  在线通道 <span className="text-neon-cyan">{onlineChannels}/{channels.length}</span>
                </div>
                <div className="rounded border border-border bg-bg-primary/50 px-3 py-2">
                  风险压力 <span className="text-warn-gold">{riskPressure === null ? "--" : `${(riskPressure * 100).toFixed(1)}%`}</span>
                </div>
                <div className="rounded border border-border bg-bg-primary/50 px-3 py-2">
                  数据源 <span className="text-up-green">{String(dataHealth.current_provider_display_name ?? "--")}</span>
                </div>
                <div className="rounded border border-border bg-bg-primary/50 px-3 py-2">
                  决策样本 <span className="text-neon-cyan">{decisionCount === null ? "--" : Math.round(decisionCount)}</span>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Database className="h-4 w-4 text-neon-cyan" />
              数据与对账
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 pt-4 text-xs font-mono">
            <div className="flex items-center justify-between rounded border border-border bg-bg-primary/40 px-3 py-2">
              <span className="text-info-gray/70">成功率</span>
              <span className={cn(successRatePct === null ? "text-info-gray/60" : "text-up-green")}>
                {successRatePct === null ? "--" : `${successRatePct.toFixed(2)}%`}
              </span>
            </div>
            <div className="flex items-center justify-between rounded border border-border bg-bg-primary/40 px-3 py-2">
              <span className="text-info-gray/70">平均延迟</span>
              <span className={cn(avgLatencyMs === null ? "text-info-gray/60" : "text-white")}>
                {avgLatencyMs === null ? "--" : `${avgLatencyMs.toFixed(1)} ms`}
              </span>
            </div>
            <div className="flex items-center justify-between rounded border border-border bg-bg-primary/40 px-3 py-2">
              <span className="text-info-gray/70">对账阻断</span>
              <Badge variant={Boolean(recon.blocked) ? "destructive" : "success"}>
                {Boolean(recon.blocked) ? "BLOCKED" : "CLEAR"}
              </Badge>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center justify-between text-info-gray/60">
              <span className="text-[10px] uppercase tracking-widest">总资产</span>
              <Wallet className="h-4 w-4" />
            </div>
            <div className="mt-3 font-orbitron text-2xl font-bold text-white">{fmtMoney(wallet.total_assets)}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center justify-between text-info-gray/60">
              <span className="text-[10px] uppercase tracking-widest">今日盈亏</span>
              <TrendingUp className="h-4 w-4" />
            </div>
            <div
              className={cn(
                "mt-3 flex items-center gap-2 font-orbitron text-2xl font-bold",
                pnl === null ? "text-info-gray/60" : pnlIsUp ? "text-up-green" : "text-down-red",
              )}
            >
              {pnl === null ? null : pnlIsUp ? <ArrowUpRight className="h-5 w-5" /> : <ArrowDownRight className="h-5 w-5" />}
              {pnl === null ? "--" : fmtMoney(pnl)}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center justify-between text-info-gray/60">
              <span className="text-[10px] uppercase tracking-widest">持仓市值</span>
              <Activity className="h-4 w-4" />
            </div>
            <div className="mt-3 font-orbitron text-2xl font-bold text-white">{fmtMoney(wallet.market_value)}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center justify-between text-info-gray/60">
              <span className="text-[10px] uppercase tracking-widest">可用资金</span>
              <ShieldCheck className="h-4 w-4" />
            </div>
            <div className="mt-3 font-orbitron text-2xl font-bold text-white">{fmtMoney(wallet.available_cash)}</div>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-[2fr_1fr]">
        <Card className="min-h-[340px]">
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              <span>仓位与执行流</span>
              {loading && <Loader2 className="h-4 w-4 animate-spin text-neon-cyan" />}
            </CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 pt-4 lg:grid-cols-2">
            <div className="space-y-2">
              <div className="text-[10px] uppercase tracking-widest text-info-gray/60">Top 持仓</div>
              <div className="space-y-2">
                {positions.length > 0 ? (
                  positions.slice(0, 6).map((item, idx) => {
                    const unrealizedPnl = toOptionalNumber(item.unrealized_pnl);
                    return (
                      <div key={`${String(item.ticker ?? "--")}-${idx}`} className="rounded border border-border bg-bg-primary/50 p-3">
                        <div className="flex items-center justify-between">
                          <span className="font-mono text-sm text-white">{String(item.ticker ?? "--")}</span>
                          <span className="text-xs text-info-gray/70">{fmtMoney(item.market_value)}</span>
                        </div>
                        <div className="mt-1 text-[11px] text-info-gray/70">
                          持仓 {fmtInt(item.quantity)} | 可卖 {fmtInt(item.available)}
                        </div>
                        <div
                          className={cn(
                            "mt-1 text-[11px]",
                            unrealizedPnl === null ? "text-info-gray/60" : unrealizedPnl >= 0 ? "text-up-green" : "text-down-red",
                          )}
                        >
                          浮盈亏 {fmtMoney(item.unrealized_pnl)}
                        </div>
                      </div>
                    );
                  })
                ) : (
                  <div className="rounded border border-dashed border-border p-4 text-xs text-info-gray/60">暂无持仓数据</div>
                )}
              </div>
            </div>

            <div className="space-y-2">
              <div className="text-[10px] uppercase tracking-widest text-info-gray/60">最近订单</div>
              <div className="space-y-2">
                {orders.length > 0 ? (
                  orders.slice(0, 8).map((item, idx) => (
                    <div key={`${String(item.request_id ?? "--")}-${idx}`} className="rounded border border-border bg-bg-primary/50 p-3">
                      <div className="flex items-center justify-between">
                        <span className="font-mono text-sm text-white">
                          {String(item.ticker ?? "--")} {String(item.side ?? "--")}
                        </span>
                        <Badge variant={String(item.status ?? "").includes("REJECT") || String(item.status ?? "").includes("FAILED") ? "destructive" : "outline"}>
                          {String(item.status ?? "--")}
                        </Badge>
                      </div>
                      <div className="mt-1 text-[11px] text-info-gray/70">
                        数量 {fmtInt(item.quantity)} @ {fmtDecimal(item.price, 3)}
                      </div>
                      <div className="mt-1 flex items-center gap-1 text-[10px] text-info-gray/60">
                        <Clock3 className="h-3 w-3" />
                        {fmtClock(item.updated_at)}
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="rounded border border-dashed border-border p-4 text-xs text-info-gray/60">暂无订单数据</div>
                )}
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="min-h-[340px]">
          <CardHeader>
            <CardTitle>风控与通道</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4 pt-4">
            <div className="rounded border border-border bg-bg-primary/40 p-3">
              <div className="mb-2 flex items-center justify-between text-xs">
                <span className="text-info-gray/70">日内回撤压力</span>
                <span
                  className={cn(
                    drawdownCurrent === null || drawdownThreshold === null
                      ? "text-info-gray/60"
                      : drawdownCurrent >= drawdownThreshold
                        ? "text-down-red"
                        : "text-up-green",
                  )}
                >
                  {fmtPct(risk.max_drawdown_current)} / {fmtPct(risk.max_drawdown_threshold)}
                </span>
              </div>
              <div className="h-1.5 rounded-full bg-bg-hover">
                <div
                  className={cn(
                    "h-full rounded-full",
                    riskPressure === null ? "bg-info-gray/40" : riskPressure >= 1 ? "bg-down-red" : "bg-warn-gold",
                  )}
                  style={{ width: `${riskPressure === null ? 0 : Math.min(Math.max(riskPressure * 100, 0), 100)}%` }}
                />
              </div>
            </div>

            <div className="space-y-2">
              {channels.map((item, idx) => {
                const status = String(item.status ?? "").toLowerCase();
                const online = status === "online";
                return (
                  <div key={`${String(item.name ?? "--")}-${idx}`} className="flex items-center justify-between rounded border border-border bg-bg-primary/40 px-3 py-2 text-xs">
                    <div className="flex items-center gap-2 text-white">
                      {online ? <Wifi className="h-3.5 w-3.5 text-up-green" /> : <WifiOff className="h-3.5 w-3.5 text-down-red" />}
                      <span>{String(item.name ?? "--")}</span>
                    </div>
                    <span className={cn("font-mono", online ? "text-up-green" : status === "paused" ? "text-warn-gold" : "text-down-red")}>
                      {status || "--"}
                    </span>
                  </div>
                );
              })}
            </div>

            <div className="rounded border border-border bg-bg-primary/40 p-3">
              <div className="mb-2 flex items-center justify-between text-xs">
                <span className="text-info-gray/70">最近告警</span>
                <span className="text-info-gray/60">{alerts.length}</span>
              </div>
              <div className="space-y-2">
                {alerts.length > 0 ? (
                  alerts.slice(0, 5).map((item, idx) => {
                    const severity = String(item.severity ?? "low").toLowerCase() as Severity;
                    return (
                      <div key={`${String(item.action ?? "--")}-${idx}`} className="rounded border border-border/60 bg-bg-primary/50 p-2 text-[11px]">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-1.5">
                            {severity === "high" ? (
                              <ShieldAlert className="h-3.5 w-3.5 text-down-red" />
                            ) : (
                              <AlertTriangle className="h-3.5 w-3.5 text-warn-gold" />
                            )}
                            <span className="text-white">{String(item.action ?? "ALERT")}</span>
                          </div>
                          <Badge variant={severityVariant(severity)}>{severityLabel(severity)}</Badge>
                        </div>
                        <div className="mt-1 text-info-gray/70">{String(item.detail ?? "")}</div>
                      </div>
                    );
                  })
                ) : (
                  <div className="text-[11px] text-info-gray/60">暂无高风险告警</div>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
};

export default Dashboard;
