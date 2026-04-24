from __future__ import annotations

import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_PAGES_DIR = PROJECT_ROOT / "src" / "frontend" / "src" / "pages"
FRONTEND_HOOKS_DIR = PROJECT_ROOT / "src" / "frontend" / "src" / "hooks"
FRONTEND_API_FILE = PROJECT_ROOT / "src" / "frontend" / "src" / "services" / "api.ts"
CRITICAL_PAGE_PLACEHOLDER_TOKENS = {
    "ExecutionMonitor.tsx": [
        "MOCK_CHANNELS",
        '<ExternalLink className="h-3 w-3 text-info-gray cursor-pointer hover:text-white" />',
        'className="opacity-0 group-hover:opacity-100 p-1 hover:text-down-red transition-all" title="刷新订单状态"',
        "const num = toNumber(value, 0);",
        "const filledQty = toNumber(order.filled_quantity ?? order.filled_qty ?? order.quantity ?? order.qty, 0);",
        "const avgPrice = toNumber(order.filled_price ?? order.avg_price ?? order.price, 0);",
        "const updatedAt = order.updated_at ?? order.update_time ?? order.timestamp ?? order.created_at ?? Date.now();",
        "latency: Math.round(toNumber(item.latency_ms, 0)),",
        "throughput: Math.round(toNumber(item.throughput, 0)),",
        "price: toNumber(item.price, 0),",
        "qty: toNumber(item.quantity ?? item.qty, 0),",
        "duration: `${(toNumber(item.holding_time, 0) / 1000).toFixed(1)}s`,",
        "latency: 0,",
        "throughput: 0,",
        "lastSync: formatClock(Date.now()),",
        "const cancelled = toNumber(cancelResult?.cancelled, 0);",
        "const failed = toNumber(cancelResult?.failed, 0);",
    ],
    "KnowledgeHub.tsx": [
        "mockKnowledge",
        "待后端接口开放",
        "fallbackSeed",
        "const relevanceRaw = Number(row.relevance ?? row.score ?? 0);",
        "const relevance = Number.isFinite(relevanceRaw) ? Math.max(0, Math.min(100, relevanceRaw)) : 0;",
        "const [updatedAt, setUpdatedAt] = useState<number>(0);",
        "total > 0 ? items.reduce((sum, item) => sum + Number(item.relevance || 0), 0) / total : 0;",
        "const highRelevance = items.filter((item) => Number(item.relevance || 0) >= 80).length;",
    ],
    "LogTerminal.tsx": [
        "useAgentStore",
        "(通过 SSE 实时推送)",
    ],
    "MemoryVault.tsx": [
        "MOCK_MEMORIES",
        "本地视图",
        "从当前视图移除",
        "relevance >= 80 ? 'HOT'",
        "const raw = toNumber(value, 0);",
        "const relevance = Math.max(0, Math.min(100, toNumber(row.relevance ?? row.score, 0)));",
        "accessCount: Math.max(0, Math.round(toNumber(row.access_count ?? row.accessCount, 0))),",
    ],
    "AuditRisk.tsx": [
        "SWITCH_ORDER.slice(0, 3).map",
        "max_drawdown_current ?? 0.024",
        "position_limit_current ?? 0.15",
        "trade_frequency_day ?? 12",
        "api_rate_limit_percent ?? 42.0",
        "const toNumber = (value: unknown, fallback = 0): number => {",
        "current: toNumber(d.max_drawdown_current) * 100",
        "current: toNumber(d.position_limit_current) * 100",
        "current: toNumber(d.trade_frequency_day)",
        "current: toNumber(d.api_rate_limit_percent)",
        "time: new Date((Number(l.timestamp) || 0) * 1000).toLocaleTimeString(),",
    ],
    "BacktestLab.tsx": [
        "mockMetrics",
        "simulateBacktest",
        "Floating Tooltip Mock",
        "蒙特卡洛接口待接入",
        "当前版本仅展示接口接入状态，不生成伪结果",
        "buildSyntheticBars",
        "DEFAULT_STRATEGY_OPTIONS",
        "totalReturn * 0.65",
        "const totalReturn = Number(metrics?.total_return ?? 0) * 100;",
        "const maxDrawdown = Number(metrics?.max_drawdown ?? 0) * 100;",
        "const sharpe = Number(metrics?.sharpe ?? 0);",
        "const winRate = Number(metrics?.win_rate ?? 0) * 100;",
        "const tradeCount = Number(metrics?.trade_count ?? 0);",
        "const turnover = Number(metrics?.turnover ?? 0);",
        "const netPnl = Number(metrics?.net_pnl ?? 0);",
        "const finalEquity = Number(summary?.final_equity ?? 0);",
        "createdAt: toNumber(report?.created_at, 0),",
        "left: toNumber(left.metrics.net_pnl, 0),",
        "leftDisplay: toNumber(left.metrics.net_pnl, 0).toFixed(2),",
        "left: asPercent(left.metrics.win_rate),",
        "left: toNumber(left.metrics.sharpe ?? left.metrics.sharpe_ratio, 0),",
        "left: asPercent(left.metrics.max_drawdown),",
        "left: toNumber(left.metrics.trade_count, 0),",
        "const createdAt = toNumber(archive.created_at, 0);",
        "const finalEquity = toNumber(backtestSummary.final_equity, 0);",
        "bestIndex: toNumber(bestResult?.index, 0),",
        "bestNetPnl: toNumber((bestResult?.metrics ?? {}).net_pnl, 0),",
    ],
    "Dashboard.tsx": [
        "const toNumber = (value: unknown, fallback = 0): number => {",
        "const num = toNumber(value, 0);",
        "`¥${toNumber(value, 0).toLocaleString(\"zh-CN\", { maximumFractionDigits: 2, minimumFractionDigits: 2 })}`;",
        "const fmtPct = (value: unknown) => `${(toNumber(value, 0) * 100).toFixed(2)}%`;",
        "const readinessScore = toNumber(overview?.readiness_score, 0);",
        "const pnl = toNumber(wallet.daily_pnl, 0);",
        "在线通道 <span className=\"text-neon-cyan\">{onlineChannels}/{channels.length || 0}</span>",
        "决策样本 <span className=\"text-neon-cyan\">{toNumber(decision.count, 0)}</span>",
        "<span className=\"text-up-green\">{toNumber(dataHealth.success_rate_pct, 0).toFixed(2)}%</span>",
        "<span className=\"text-white\">{toNumber(dataHealth.avg_latency_ms, 0).toFixed(1)} ms</span>",
        "持仓 {toNumber(item.quantity, 0)} | 可卖 {toNumber(item.available, 0)}",
        "数量 {toNumber(item.quantity, 0)} @ {toNumber(item.price, 0).toFixed(3)}",
    ],
    "SystemConfig.tsx": [
        "const [mcpStatus, setMcpStatus]",
        "ConfigSection title=\"MCP 控制\"",
        "setTimeout(() => setMcpStatus('RUNNING'), 1500)",
        "temperature: Number(config.temperature ?? 0.7),",
        "temperature: Number(e.target.value) || 0",
        "{enabled ? 'enabled' : 'disabled'} / priority {Number(provider.priority ?? 100)}",
    ],
    "MarketTerminal.tsx": [
        "TradingView 行情图表",
        "const successRateRaw = Number(healthData?.success_rate ?? 0);",
        "success_rate: 0,",
        "avg_latency_ms: 0,",
        "const successRate = Number(health?.success_rate ?? 0);",
        "(quote.change_pct ?? 0) >= 0 ? '+' : ''",
        "(quote.change_pct ?? 0).toFixed(2)%",
        "Number(health?.avg_latency_ms || 0) > 100",
        "{Number(health?.avg_latency_ms || 0)} ms",
    ],
    "StrategyMatrix.tsx": ["s.metrics?.win_rate || 0.5", "s.metrics?.profit_loss_ratio || 1.5", "s.metrics?.quality_score || 0.7"],
    "EvolutionCenter.tsx": [
        "根据 ${event.type} 事件评估版本门禁与参数漂移。",
        "等待更多数据后执行动作。",
        "version_gate as { passed?: boolean } | undefined)?.passed",
        "No metric context.",
        "Decision not provided.",
        "Action not provided.",
        "Unknown Strategy",
        "No strategy description.",
        "${event.strategyName} ${event.type}",
        "strategy.maxDrawdown <= 0.2",
        "toNumber(rawOoda.trades, 0)",
        "toNumber(rawOoda.pnl, 0)",
        "toNumber(rawOoda.deviations, 0)",
        "toNumber(ooda?.trades, 0)",
        "toNumber(ooda?.pnl, 0)",
        "toNumber(ooda?.deviations, 0)",
        "return new Date().toISOString();",
        "event.timestamp.startsWith(new Date().toISOString().split('T')[0])",
        "clamp(toNumber(mergedMetrics.max_drawdown, 0), 0, 1)",
        "toNumber(mergedMetrics.sharpe_ratio ?? mergedMetrics.sharpe, 0)",
        "normalizeRatio(mergedMetrics.win_rate)",
        "Math.max(0, Math.round(toNumber(mergedMetrics.trade_count, 0)))",
        "toNumber(mergedMetrics.net_pnl ?? mergedMetrics.total_pnl, 0)",
        "return fromOrigin[raw] ?? 'DERIVED';",
        "return map[raw] ?? 'ACTIVE';",
        "version: String(item.version ?? 1),",
        "v{strategy.version}",
        "v{node.version}",
    ],
    "AgentWorkshop.tsx": [
        "1.2s",
        "4.2k",
        "92%",
        ".map((item) => Number(item.lastUpdate || 0))",
        "const num = toNumber(value, 0);",
        "timestamp: timestamp > 0 ? new Date(timestamp).toLocaleTimeString() : '--',",
        "const pnlValue = toNumber(wallet?.daily_pnl ?? wallet?.total_pnl, 0);",
        "{pnl >= 0 ? '+' : ''}{pnl.toFixed(2)} USD",
    ],
}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_frontend_pages_no_direct_fetch_calls() -> None:
    offenders: list[str] = []
    for file_path in FRONTEND_PAGES_DIR.rglob("*.tsx"):
        content = _read_text(file_path)
        if "fetch(" in content:
            offenders.append(str(file_path.relative_to(PROJECT_ROOT)))

    assert offenders == [], f"页面层仍存在直连 fetch: {offenders}"


def test_frontend_pages_no_api_base_env_access() -> None:
    offenders: list[str] = []
    for file_path in FRONTEND_PAGES_DIR.rglob("*.tsx"):
        content = _read_text(file_path)
        if "VITE_API_BASE_URL" in content:
            offenders.append(str(file_path.relative_to(PROJECT_ROOT)))

    assert offenders == [], f"页面层仍存在 API_BASE 直连: {offenders}"


def test_frontend_hooks_no_api_base_env_access() -> None:
    offenders: list[str] = []
    for file_path in FRONTEND_HOOKS_DIR.rglob("*.ts*"):
        content = _read_text(file_path)
        if "VITE_API_BASE_URL" in content:
            offenders.append(str(file_path.relative_to(PROJECT_ROOT)))

    assert offenders == [], f"Hook 层仍存在 API_BASE 直连: {offenders}"


def test_api_layer_public_exports_have_jsdoc() -> None:
    content = _read_text(FRONTEND_API_FILE)

    required_exports = [
        "export class ApiClientError",
        "export function apiUrl",
        "export async function apiRequest",
        "export const api =",
        "export const monitorApi =",
        "export const strategyApi =",
        "export const tradingApi =",
        "export const systemApi =",
        "export const streamApi =",
    ]

    for export_token in required_exports:
        pattern = re.compile(rf"/\*\*[\s\S]*?\*/\s*{re.escape(export_token)}")
        assert pattern.search(content), f"缺少 JSDoc: {export_token}"


def test_api_layer_domain_methods_have_jsdoc() -> None:
    content = _read_text(FRONTEND_API_FILE)

    required_methods = [
        "getOverview",
        "getRisk",
        "getAuditLogs",
        "toggleRiskSwitch",
        "getStatus",
        "getQuote",
        "getKline",
        "getDataHealth",
        "getVersions",
        "getHistory",
        "getBacktests",
        "getBacktestById",
        "runBacktest",
        "runBacktestGrid",
        "getVersionDiff",
        "transitionVersion",
        "getKnowledge",
        "ingestKnowledge",
        "deleteKnowledge",
        "getMemoryOverrides",
        "promoteMemory",
        "demoteMemory",
        "forgetMemory",
        "getSnapshot",
        "getActiveOrders",
        "syncOrders",
        "placeDirectOrder",
        "switchChannel",
        "cancelAllOrders",
        "getConfig",
        "updateConfig",
        "getLlmConfig",
        "updateLlmConfig",
        "getRuntime",
        "getThsHostDiagnosis",
        "getThsBridgeState",
        "startThsBridge",
        "stopThsBridge",
        "getDataflowProviders",
        "switchDataflowProvider",
        "testWechatNotification",
        "getEventsUrl",
    ]

    for method_name in required_methods:
        pattern = re.compile(rf"/\*\*[\s\S]*?\*/\s*{re.escape(method_name)}\s*:")
        assert pattern.search(content), f"缺少 JSDoc: {method_name}"


def test_critical_frontend_pages_no_placeholder_logic() -> None:
    offenders: list[str] = []
    for file_name, tokens in CRITICAL_PAGE_PLACEHOLDER_TOKENS.items():
        file_path = FRONTEND_PAGES_DIR / file_name
        content = _read_text(file_path)
        for token in tokens:
            if token in content:
                offenders.append(f"{file_name} -> {token}")

    assert offenders == [], f"关键页面仍包含占位实现: {offenders}"


def test_critical_frontend_pages_wire_real_actions_via_api_layer() -> None:
    checks = {
        "AgentWorkshop.tsx": ["monitorApi.getOverview", "monitorApi.getAuditLogs"],
        "AuditRisk.tsx": ["monitorApi.toggleRiskSwitch"],
        "KnowledgeHub.tsx": ["strategyApi.ingestKnowledge", "strategyApi.deleteKnowledge"],
        "MemoryVault.tsx": [
            "strategyApi.getKnowledge",
            "strategyApi.getMemoryOverrides",
            "strategyApi.promoteMemory",
            "strategyApi.demoteMemory",
            "strategyApi.forgetMemory",
        ],
        "ExecutionMonitor.tsx": ["tradingApi.syncOrders", "apiUrl('/api/system/runtime')"],
        "LogTerminal.tsx": ["monitorApi.getAuditLogs"],
        "MarketTerminal.tsx": ["tradingApi.placeDirectOrder"],
        "BacktestLab.tsx": ["strategyApi.getVersions", "strategyApi.runBacktestGrid", "monitorApi.getKline"],
        "EvolutionCenter.tsx": [
            "strategyApi.getVersions",
            "strategyApi.getHistory",
            "strategyApi.getBacktests",
            "strategyApi.getVersionDiff",
        ],
        "SystemConfig.tsx": [
            "systemApi.getThsBridgeState",
            "systemApi.startThsBridge",
            "systemApi.stopThsBridge",
        ],
    }

    offenders: list[str] = []
    for file_name, tokens in checks.items():
        file_path = FRONTEND_PAGES_DIR / file_name
        content = _read_text(file_path)
        for token in tokens:
            if token not in content:
                offenders.append(f"{file_name} missing {token}")

    assert offenders == [], f"关键页面未接入真实动作 API: {offenders}"


def test_stream_hook_uses_api_layer_url_builder() -> None:
    hook_path = FRONTEND_HOOKS_DIR / "useSSE.ts"
    content = _read_text(hook_path)

    assert "streamApi.getEventsUrl()" in content, "useSSE 必须通过 streamApi.getEventsUrl 构建地址"
    assert "VITE_API_BASE_URL" not in content, "useSSE 不允许直连 VITE_API_BASE_URL"
