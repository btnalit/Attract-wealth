/**
 * 前端 API 鉴权工具。
 *
 * 设计：
 * - API Key 来源优先级：setApiKey() 设置的运行时值 > localStorage > vite 环境变量。
 * - 与后端 src/routers/auth.py 的 require_api_key 对接：注入 X-API-Key header。
 * - SSE/EventSource 不支持自定义 header，改用 query param（见 appendAuthQuery）。
 * - 未配置 key 时返回空字符串，鉴权依赖在后端默认关闭（开发场景兼容）。
 */

const STORAGE_KEY = "laicai_api_key";

/**
 * 读取构建期注入的 API Key（vite env）。
 * 生产打包时可通过 VITE_API_KEY 注入；未配置则为空。
 */
function buildTimeKey(): string {
  return ((import.meta as unknown as { env?: Record<string, string> }).env?.VITE_API_KEY ?? "").trim();
}

/**
 * 获取当前生效的 API Key。
 * 优先级：运行时内存 > localStorage > 构建期 env。
 */
export function getApiKey(): string {
  if (typeof window === "undefined" || !window.localStorage) {
    return buildTimeKey();
  }
  const stored = (window.localStorage.getItem(STORAGE_KEY) ?? "").trim();
  if (stored) {
    return stored;
  }
  return buildTimeKey();
}

/**
 * 运行时设置/更新 API Key（持久化到 localStorage）。
 * 用于前端"设置 API Key"界面或 401 后引导用户输入。
 */
export function setApiKey(key: string): void {
  const trimmed = (key ?? "").trim();
  if (typeof window !== "undefined" && window.localStorage) {
    if (trimmed) {
      window.localStorage.setItem(STORAGE_KEY, trimmed);
    } else {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  }
}

/**
 * 判断鉴权是否已配置（有 key 可用）。
 */
export function hasApiKey(): boolean {
  return getApiKey().length > 0;
}

/**
 * 构建鉴权 header 对象（供 fetch 使用）。
 * 无 key 时返回空对象（不注入），保持与未启用鉴权的后端兼容。
 */
export function authHeaders(): Record<string, string> {
  const key = getApiKey();
  return key ? { "X-API-Key": key } : {};
}

/**
 * 为不支持自定义 header 的端点（如 EventSource）追加鉴权 query param。
 * 返回新的 URL 字符串；无 key 时原样返回。
 *
 * 注意：query param 传输 token 会出现在 URL/日志中，安全性低于 header，
 * 仅用于 EventSource 等无法设置 header 的场景。
 */
export function appendAuthQuery(url: string): string {
  const key = getApiKey();
  if (!key) {
    return url;
  }
  const sep = url.includes("?") ? "&" : "?";
  return `${url}${sep}api_key=${encodeURIComponent(key)}`;
}
