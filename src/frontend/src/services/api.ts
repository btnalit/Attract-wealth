import type {
  CancelAllOrdersRequest,
  ChannelSwitchRequest,
  DirectOrderRequest,
  LLMRuntimeConfigRequest,
  NotificationTestRequest,
  StrategyBacktestGridRequest,
  StrategyBacktestRequest,
  StrategyTransitionRequest,
  THSBridgeStartRequest,
  THSBridgeStopRequest,
} from "../api/generated/openapi-types";

/**
 * API 成功包络。
 */
export interface ApiOk<T> {
  ok: true;
  code: string;
  data: T;
}

/**
 * API 失败包络。
 */
export interface ApiErr {
  ok: false;
  code: string;
  message: string;
  details: Record<string, unknown>;
  meta?: Record<string, unknown>;
}

/**
 * 查询参数值类型。
 */
export type ApiQueryValue = string | number | boolean | null | undefined;

/**
 * 查询参数字典类型。
 */
export type ApiQuery = Record<string, ApiQueryValue>;

/**
 * 统一 API 客户端异常，承载后端业务码与 HTTP 状态码。
 */
export class ApiClientError extends Error {
  code: string;
  status: number;
  details: Record<string, unknown>;

  constructor(message: string, code: string, status: number, details: Record<string, unknown> = {}) {
    super(message);
    this.name = "ApiClientError";
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "";

const hasOwn = <T extends object>(obj: T, key: string): boolean => Object.prototype.hasOwnProperty.call(obj, key);

const isObjectRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null;

const isEnvelopePayload = (value: unknown): value is ApiOk<unknown> | ApiErr =>
  isObjectRecord(value) && hasOwn(value, "ok") && typeof value.ok === "boolean";

/**
 * 构建请求 URL（自动拼接 `VITE_API_BASE_URL` 与 query）。
 */
function buildUrl(path: string, query?: ApiQuery): string {
  const base = path.startsWith("http") ? path : `${API_BASE}${path}`;
  if (!query || Object.keys(query).length === 0) {
    return base;
  }

  const search = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") {
      return;
    }
    search.set(key, String(value));
  });

  const suffix = search.toString();
  return suffix ? `${base}?${suffix}` : base;
}

/**
 * 将 API 路径转换为可直接打开的绝对 URL。
 */
export function apiUrl(path: string, query?: ApiQuery): string {
  return buildUrl(path, query);
}

async function parseBody<T>(resp: Response): Promise<T | null> {
  const raw = await resp.text();
  if (!raw) {
    return null;
  }
  return JSON.parse(raw) as T;
}

/**
 * 统一请求入口。
 *
 * 行为说明：
 * - 若响应为标准包络：`ok=true` 返回 `data`，`ok=false` 抛 `ApiClientError`。
 * - 若响应为非包络历史结构：直接返回原始 payload（兼容旧接口）。
 * - 若响应体为空且 HTTP 成功：返回空对象。
 */
export async function apiRequest<T>(path: string, init: RequestInit = {}, query?: ApiQuery): Promise<T> {
  const resp = await fetch(buildUrl(path, query), {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init.headers || {}),
    },
  });

  const payload = await parseBody<unknown>(resp);

  if (!payload) {
    if (resp.ok) {
      return {} as T;
    }
    throw new ApiClientError("空响应", "EMPTY_RESPONSE", resp.status);
  }

  if (isEnvelopePayload(payload)) {
    if (payload.ok) {
      return payload.data as T;
    }
    const err = payload as ApiErr;
    throw new ApiClientError(
      err.message || "请求失败",
      err.code || "REQUEST_FAILED",
      resp.status,
      err.details || {}
    );
  }

  if (!resp.ok) {
    const detailPayload = isObjectRecord(payload) ? payload : {};
    const errorMessage = isObjectRecord(payload)
      ? String(payload.message ?? payload.detail ?? `HTTP ${resp.status}`)
      : `HTTP ${resp.status}`;
    throw new ApiClientError(errorMessage, "HTTP_ERROR", resp.status, detailPayload);
  }

  return payload as T;
}

/**
 * 统一 HTTP 方法封装。
 */
export const api = {
  /**
   * 发送 GET 请求。
   */
  get: <T>(path: string, query?: ApiQuery) => apiRequest<T>(path, { method: "GET" }, query),
  /**
   * 发送 POST 请求。
   */
  post: <T>(path: string, body?: unknown, headers?: Record<string, string>) =>
    apiRequest<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body), headers }),
  /**
   * 发送 PUT 请求。
   */
  put: <T>(path: string, body?: unknown, headers?: Record<string, string>) =>
    apiRequest<T>(path, { method: "PUT", body: body === undefined ? undefined : JSON.stringify(body), headers }),
};

/**
 * API 层通用对象（用于未知扩展字段）。
 */
export type ApiLooseObject = Record<string, unknown>;

/**
 * 风控开关切换请求。
 */
export interface RiskTogglePayload {
  name: string;
  enabled: boolean;
}

/**
 * 通道状态结构。
 */
export interface MonitorStatusPayload {
  name?: string;
  status?: string;
  latency_ms?: number;
  throughput?: number;
  last_sync?: string | number;
  [key: string]: unknown;
}

/**
 * 风险快照结构。
 */
export interface MonitorRiskPayload {
  max_drawdown_current?: number;
  [key: string]: unknown;
}

/**
 * 监控总览钱包结构。
 */
export interface MonitorOverviewWalletPayload {
  total_assets?: number;
  available_cash?: number;
  market_value?: number;
  daily_pnl?: number;
  total_pnl?: number;
  account_name?: string;
  account_type?: string;
  updated_at?: number;
  [key: string]: unknown;
}

/**
 * 监控总览结构。
 */
export interface MonitorOverviewPayload {
  generated_at?: number;
  readiness_score?: number;
  readiness_level?: string;
  wallet?: MonitorOverviewWalletPayload;
  risk?: MonitorRiskPayload;
  channels?: MonitorStatusPayload[];
  data_health?: ApiLooseObject;
  reconciliation_guard?: ApiLooseObject;
  positions?: TradingPositionPayload[];
  recent_orders?: ApiLooseObject[];
  alerts?: ApiLooseObject[];
  decision_summary?: ApiLooseObject;
  counts?: ApiLooseObject;
  [key: string]: unknown;
}

/**
 * 资金快照结构。
 */
export interface TradingBalancePayload {
  total_assets?: number;
  daily_pnl?: number;
  market_value?: number;
  available_cash?: number;
  [key: string]: unknown;
}

/**
 * 持仓快照结构。
 */
export interface TradingPositionPayload {
  ticker?: string;
  symbol?: string;
  market_value?: number;
  unrealized_pnl?: number;
  [key: string]: unknown;
}

/**
 * 策略快照结构。
 */
export interface TradingStrategyPayload {
  name?: string;
  quality_score?: number;
  status?: string;
  daily_return?: number;
  [key: string]: unknown;
}

/**
 * 订单快照结构。
 */
export interface TradingSnapshotOrderPayload {
  order_id?: string;
  id?: string;
  ticker?: string;
  symbol?: string;
  side?: string;
  price?: number;
  filled_price?: number;
  avg_price?: number;
  quantity?: number;
  qty?: number;
  filled_quantity?: number;
  filled_qty?: number;
  status?: string;
  updated_at?: number | string;
  update_time?: number | string;
  timestamp?: number | string;
  created_at?: number | string;
  [key: string]: unknown;
}

/**
 * 交易通道信息结构。
 */
export interface TradingSnapshotChannelInfo {
  name?: string;
  status?: string;
  hwnd?: string | number;
  title?: string;
  [key: string]: unknown;
}

/**
 * 交易快照结构。
 */
export interface TradingSnapshotPayload {
  balance?: TradingBalancePayload;
  positions?: TradingPositionPayload[];
  strategies?: TradingStrategyPayload[];
  channel_info?: TradingSnapshotChannelInfo;
  orders?: TradingSnapshotOrderPayload[];
  [key: string]: unknown;
}

/**
 * 系统配置结构。
 */
export interface SystemConfigPayload {
  tushare_token?: string;
  wechat_webhook?: string;
  dingtalk_secret?: string;
  [key: string]: unknown;
}

/**
 * 单个数据源状态结构。
 */
export interface DataflowProviderPayload {
  name?: string;
  display_name?: string;
  enabled?: boolean;
  current?: boolean;
  priority?: number;
  requests?: number;
  success?: number;
  failure?: number;
  error_rate?: number;
  last_error_code?: string;
  last_latency_ms?: number;
  [key: string]: unknown;
}

/**
 * 数据源目录结构。
 */
export interface DataflowProvidersPayload {
  current_provider?: string;
  current_provider_display_name?: string;
  providers?: DataflowProviderPayload[];
  summary?: ApiLooseObject;
  quality?: ApiLooseObject;
  tuning?: ApiLooseObject;
  runtime_config?: ApiLooseObject;
  [key: string]: unknown;
}

/**
 * 数据源切换请求结构。
 */
export interface DataflowProviderSwitchPayload {
  provider: string;
  persist?: boolean;
}

/**
 * LLM 配置读取结构。
 */
export interface LlmConfigPayload {
  config?: LLMRuntimeConfigRequest;
  base_url?: string;
  model?: string;
  temperature?: number;
  api_key?: string;
  [key: string]: unknown;
}

/**
 * THS runtime 探针结构。
 */
export interface ThsHostRuntimeProbePayload {
  reachable?: boolean;
  runtime_ok?: boolean;
  runtime?: ApiLooseObject;
  error?: string;
  [key: string]: unknown;
}

/**
 * THS 宿主触发诊断结构。
 */
export interface ThsHostTriggerDiagnosisPayload {
  stage?: string;
  status?: string;
  summary?: string;
  blockers?: string[];
  suggestions?: string[];
  facts?: ApiLooseObject;
  [key: string]: unknown;
}

/**
 * xiadan UI 诊断结构。
 */
export interface ThsXiadanUiContextPayload {
  running?: boolean;
  process_count?: number;
  strategy_page_open?: boolean;
  strategy_window_keywords?: string[];
  strategy_related_windows?: string[];
  window_titles?: string[];
  processes?: ApiLooseObject[];
  error?: string;
  [key: string]: unknown;
}

/**
 * THS 宿主诊断结构。
 */
export interface ThsHostDiagnosisPayload {
  checked_at?: number;
  status?: string;
  ready?: boolean;
  host?: string;
  port?: number;
  timeout_s?: number;
  ths_root?: string;
  xiadan_running?: boolean | null;
  xiadan_process_check?: ApiLooseObject;
  xiadan_ui_context?: ThsXiadanUiContextPayload;
  account_context?: ApiLooseObject;
  runtime_probe?: ThsHostRuntimeProbePayload;
  host_observability?: ApiLooseObject;
  host_trigger_diagnosis?: ThsHostTriggerDiagnosisPayload;
  hints?: string[];
  [key: string]: unknown;
}

/**
 * THS Bridge 状态结构。
 */
export interface ThsBridgeStatePayload {
  ths_bridge?: ApiLooseObject;
  [key: string]: unknown;
}

/**
 * 知识条目摄入请求结构。
 */
export interface StrategyKnowledgeIngestPayload {
  type: "pattern" | "lesson" | "rule";
  title: string;
  content: string;
  tags?: string[];
  priority?: number;
  context?: ApiLooseObject;
}

/**
 * 知识条目删除请求结构。
 */
export interface StrategyKnowledgeDeletePayload {
  id: string;
}

/**
 * 记忆层级动作请求结构。
 */
export interface StrategyMemoryTierActionPayload {
  id: string;
  current_tier: "HOT" | "WARM" | "COLD";
}

/**
 * 记忆遗忘动作请求结构。
 */
export interface StrategyMemoryForgetPayload {
  id: string;
}

/**
 * Monitor 域 API。
 */
export const monitorApi = {
  /**
   * 获取驾驶舱总览聚合数据。
   */
  getOverview: <T = MonitorOverviewPayload>() => api.get<T>("/api/v1/monitor/overview"),
  /**
   * 获取风险指标快照。
   */
  getRisk: <T = MonitorRiskPayload>() => api.get<T>("/api/v1/monitor/risk"),
  /**
   * 获取风控审计日志。
   */
  getAuditLogs: <T = ApiLooseObject[]>(limit = 20) => api.get<T>("/api/v1/monitor/audit", { limit }),
  /**
   * 切换风险开关。
   */
  toggleRiskSwitch: <T = ApiLooseObject>(payload: RiskTogglePayload) =>
    api.post<T>("/api/v1/monitor/risk/toggle", payload),
  /**
   * 获取通道状态。
   */
  getStatus: <T = MonitorStatusPayload[] | MonitorStatusPayload>() => api.get<T>("/api/v1/monitor/status"),
  /**
   * 获取行情报价。
   */
  getQuote: <T = ApiLooseObject>(symbol: string) => api.get<T>(`/api/v1/monitor/quote/${symbol}`),
  /**
   * 获取历史 K 线。
   */
  getKline: <T = ApiLooseObject[]>(ticker: string, limit = 120, interval = "daily") =>
    api.get<T>(`/api/v1/monitor/kline/${ticker}`, { limit, interval }),
  /**
   * 获取数据源健康状态。
   */
  getDataHealth: <T = ApiLooseObject>() => api.get<T>("/api/v1/monitor/data-health"),
};

/**
 * Strategy 域 API。
 */
export const strategyApi = {
  /**
   * 查询策略版本列表。
   */
  getVersions: <T = ApiLooseObject>(limit?: number) => api.get<T>("/api/strategy/versions", { limit }),
  /**
   * 查询策略演进历史。
   */
  getHistory: <T = ApiLooseObject>() => api.get<T>("/api/strategy/history"),
  /**
   * 查询回测列表。
   */
  getBacktests: <T = ApiLooseObject>(limit?: number) => api.get<T>("/api/strategy/backtests", { limit }),
  /**
   * 查询回测详情。
   */
  getBacktestById: <T = ApiLooseObject>(id: string) => api.get<T>(`/api/strategy/backtests/${id}`),
  /**
   * 启动一次回测。
   */
  runBacktest: <T = ApiLooseObject>(payload: StrategyBacktestRequest) => api.post<T>("/api/strategy/backtest", payload),
  /**
   * 启动一次参数网格回测（用于蒙特卡洛/参数分布模拟）。
   */
  runBacktestGrid: <T = ApiLooseObject>(payload: StrategyBacktestGridRequest) =>
    api.post<T>("/api/strategy/backtest/grid", payload),
  /**
   * 查询策略版本差异。
   */
  getVersionDiff: <T = ApiLooseObject>(id: string) => api.get<T>(`/api/strategy/versions/${id}/diff`),
  /**
   * 迁移策略版本状态。
   */
  transitionVersion: <T = ApiLooseObject>(id: string, payload: StrategyTransitionRequest) =>
    api.post<T>(`/api/strategy/versions/${id}/transition`, payload),
  /**
   * 查询知识库条目。
   */
  getKnowledge: <T = ApiLooseObject>(type?: string, q?: string) =>
    api.get<T>("/api/strategy/knowledge", { type, q }),
  /**
   * 摄入一条知识到知识库。
   */
  ingestKnowledge: <T = ApiLooseObject>(payload: StrategyKnowledgeIngestPayload) =>
    api.post<T>("/api/strategy/knowledge/ingest", payload),
  /**
   * 删除一条知识条目。
   */
  deleteKnowledge: <T = ApiLooseObject>(payload: StrategyKnowledgeDeletePayload) =>
    api.post<T>("/api/strategy/knowledge/delete", payload),
  /**
   * 查询记忆层级覆盖与遗忘状态。
   */
  getMemoryOverrides: <T = ApiLooseObject>() => api.get<T>("/api/strategy/memory/overrides"),
  /**
   * 提升一条记忆层级（COLD->WARM->HOT）。
   */
  promoteMemory: <T = ApiLooseObject>(payload: StrategyMemoryTierActionPayload) =>
    api.post<T>("/api/strategy/memory/promote", payload),
  /**
   * 降低一条记忆层级（HOT->WARM->COLD）。
   */
  demoteMemory: <T = ApiLooseObject>(payload: StrategyMemoryTierActionPayload) =>
    api.post<T>("/api/strategy/memory/demote", payload),
  /**
   * 遗忘一条记忆（仅隐藏标记）。
   */
  forgetMemory: <T = ApiLooseObject>(payload: StrategyMemoryForgetPayload) =>
    api.post<T>("/api/strategy/memory/forget", payload),
};

/**
 * Trading 域 API。
 */
export const tradingApi = {
  /**
   * 获取交易快照。
   */
  getSnapshot: <T = TradingSnapshotPayload>() => api.get<T>("/api/trading/snapshot"),
  /**
   * 获取活动订单列表。
   */
  getActiveOrders: <T = ApiLooseObject[]>(limit = 50) => api.get<T>("/api/trading/orders/active", { limit }),
  /**
   * 同步订单状态。
   */
  syncOrders: <T = ApiLooseObject>() => api.post<T>("/api/trading/orders/sync"),
  /**
   * 提交直下单请求。
   */
  placeDirectOrder: <T = ApiLooseObject>(payload: DirectOrderRequest) =>
    api.post<T>("/api/trading/orders/direct", payload),
  /**
   * 切换交易通道。
   */
  switchChannel: <T = ApiLooseObject>(payload: ChannelSwitchRequest) =>
    api.post<T>("/api/trading/channel/switch", payload),
  /**
   * 批量撤销活动订单。
   */
  cancelAllOrders: <T = ApiLooseObject>(payload: CancelAllOrdersRequest) =>
    api.post<T>("/api/trading/orders/cancel-all", payload),
};

/**
 * System 域 API。
 */
export const systemApi = {
  /**
   * 获取系统配置。
   */
  getConfig: <T = SystemConfigPayload>() => api.get<T>("/api/system/config"),
  /**
   * 更新系统配置。
   */
  updateConfig: <T = ApiLooseObject>(payload: ApiLooseObject) => api.put<T>("/api/system/config", payload),
  /**
   * 获取 LLM 配置。
   */
  getLlmConfig: <T = LlmConfigPayload>() => api.get<T>("/api/system/llm/config"),
  /**
   * 更新 LLM 配置。
   */
  updateLlmConfig: <T = ApiLooseObject>(payload: LLMRuntimeConfigRequest) => api.put<T>("/api/system/llm/config", payload),
  /**
   * 获取系统运行时状态。
   */
  getRuntime: <T = ApiLooseObject>() => api.get<T>("/api/system/runtime"),
  /**
   * 获取 THS 宿主 runtime 诊断信息。
   */
  getThsHostDiagnosis: <T = ThsHostDiagnosisPayload>(query?: ApiQuery) =>
    api.get<T>("/api/system/ths-host/diagnosis", query),
  /**
   * 获取 THS Bridge 当前状态。
   */
  getThsBridgeState: <T = ThsBridgeStatePayload>() => api.get<T>("/api/system/ths-bridge"),
  /**
   * 启动 THS Bridge。
   */
  startThsBridge: <T = ApiLooseObject>(payload: THSBridgeStartRequest) =>
    api.post<T>("/api/system/ths-bridge/start", payload),
  /**
   * 停止 THS Bridge。
   */
  stopThsBridge: <T = ApiLooseObject>(payload: THSBridgeStopRequest) =>
    api.post<T>("/api/system/ths-bridge/stop", payload),
  /**
   * 获取数据源目录与当前主源状态。
   */
  getDataflowProviders: <T = DataflowProvidersPayload>() => api.get<T>("/api/system/dataflow/providers"),
  /**
   * 切换当前主数据源。
   */
  switchDataflowProvider: <T = DataflowProvidersPayload>(payload: DataflowProviderSwitchPayload) =>
    api.post<T>("/api/system/dataflow/provider/use", payload),
  /**
   * 发送企业微信测试通知。
   */
  testWechatNotification: <T = ApiLooseObject>(payload: NotificationTestRequest) =>
    api.post<T>("/api/system/notification/test/wechat", payload),
};

/**
 * Stream 域 API。
 */
export const streamApi = {
  /**
   * 获取统一 SSE 事件流地址。
   */
  getEventsUrl: () => apiUrl("/api/v1/stream/events"),
};
