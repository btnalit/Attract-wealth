export interface ApiOk<T> {
  ok: true;
  code: string;
  data: T;
}

export interface ApiErr {
  ok: false;
  code: string;
  message: string;
  details: Record<string, unknown>;
  meta?: Record<string, unknown>;
}

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

function buildUrl(path: string, query?: Record<string, string | number | boolean | undefined>) {
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

async function parseBody<T>(resp: Response): Promise<T | null> {
  const raw = await resp.text();
  if (!raw) {
    return null;
  }
  return JSON.parse(raw) as T;
}

export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
  query?: Record<string, string | number | boolean | undefined>
): Promise<T> {
  const resp = await fetch(buildUrl(path, query), {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init.headers || {}),
    },
  });

  const payload = await parseBody<ApiOk<T> | ApiErr>(resp);

  if (!payload) {
    if (resp.ok) {
      return {} as T;
    }
    throw new ApiClientError("空响应", "EMPTY_RESPONSE", resp.status);
  }

  if ("ok" in payload && payload.ok === true) {
    return payload.data;
  }

  const err = payload as ApiErr;
  throw new ApiClientError(err.message || "请求失败", err.code || "REQUEST_FAILED", resp.status, err.details || {});
}

export const api = {
  get: <T>(path: string, query?: Record<string, string | number | boolean | undefined>) =>
    apiRequest<T>(path, { method: "GET" }, query),
  post: <T>(path: string, body?: unknown, headers?: Record<string, string>) =>
    apiRequest<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body), headers }),
  put: <T>(path: string, body?: unknown, headers?: Record<string, string>) =>
    apiRequest<T>(path, { method: "PUT", body: body === undefined ? undefined : JSON.stringify(body), headers }),
};
