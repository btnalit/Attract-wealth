import { describe, expect, it } from "vitest";

import {
  OPENAPI_COMPONENT_SCHEMA_NAMES,
  OPENAPI_PATH_METHODS,
  OPENAPI_REQUEST_BODY_SCHEMAS,
  OPENAPI_SCHEMA_HASH,
} from "../api/generated/openapi-types";
import { apiUrl } from "./api";

describe("apiUrl", () => {
  it("builds query string and skips empty values", () => {
    const url = apiUrl("/api/system/runtime", {
      limit: 10,
      enabled: true,
      ignored: "",
      nil: null,
    });

    expect(url).toContain("/api/system/runtime");
    const params = new URLSearchParams(url.split("?")[1] || "");
    expect(params.get("limit")).toBe("10");
    expect(params.get("enabled")).toBe("true");
    expect(params.has("ignored")).toBe(false);
    expect(params.has("nil")).toBe(false);
  });
});

describe("openapi contract artifact", () => {
  it("exposes canonical llm config path and excludes legacy alias", () => {
    expect(OPENAPI_SCHEMA_HASH).toMatch(/^[a-f0-9]{64}$/);
    const pathMap = OPENAPI_PATH_METHODS as Record<string, readonly string[]>;
    expect(pathMap["/api/system/llm/config"]).toContain("get");
    expect(pathMap["/api/system/llm-config"]).toBeUndefined();
  });

  it("exposes schema-level contract metadata for key write APIs", () => {
    expect(OPENAPI_COMPONENT_SCHEMA_NAMES).toContain("LLMRuntimeConfigRequest");
    expect(OPENAPI_COMPONENT_SCHEMA_NAMES).toContain("StrategyBacktestRequest");
    expect(OPENAPI_REQUEST_BODY_SCHEMAS["/api/system/llm/config"]?.put).toBe("LLMRuntimeConfigRequest");
    expect(OPENAPI_REQUEST_BODY_SCHEMAS["/api/trading/orders/direct"]?.post).toBe("DirectOrderRequest");
  });
});
