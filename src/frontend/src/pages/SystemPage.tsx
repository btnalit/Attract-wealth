import { useCallback, useEffect, useState } from "react";
import { CyberpunkLayout } from "../components/CyberpunkLayout";
import { ApiClientError, api } from "../services/api";

interface LlmConfigForm {
  provider_name: string;
  base_url: string;
  model: string;
  quick_model: string;
  deep_model: string;
  timeout_s: number;
  max_tokens: number;
  temperature: number;
  api_key: string;
}

function dump(value: unknown) {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export function SystemPage() {
  const [llmForm, setLlmForm] = useState<LlmConfigForm>({
    provider_name: "custom",
    base_url: "",
    model: "",
    quick_model: "",
    deep_model: "",
    timeout_s: 120,
    max_tokens: 4096,
    temperature: 0.7,
    api_key: "",
  });
  const [llmMeta, setLlmMeta] = useState<Record<string, unknown> | null>(null);
  const [bridge, setBridge] = useState<Record<string, unknown> | null>(null);
  const [preflight, setPreflight] = useState<Record<string, unknown> | null>(null);
  const [profiles, setProfiles] = useState<Record<string, unknown> | null>(null);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [working, setWorking] = useState(false);

  const load = useCallback(async () => {
    try {
      const [llmPayload, bridgePayload, preflightPayload, profilesPayload] = await Promise.all([
        api.get<Record<string, unknown>>("/api/system/llm/config"),
        api.get<Record<string, unknown>>("/api/system/ths-bridge"),
        api.get<Record<string, unknown>>("/api/system/preflight"),
        api.get<Record<string, unknown>>("/api/system/dataflow/profiles"),
      ]);

      setLlmMeta(llmPayload);
      setBridge(bridgePayload);
      setPreflight(preflightPayload);
      setProfiles(profilesPayload);

      const cfg = (llmPayload.config as Record<string, unknown>) || {};
      setLlmForm((prev) => ({
        ...prev,
        provider_name: String(cfg.provider_name || prev.provider_name || "custom"),
        base_url: String(cfg.base_url || ""),
        model: String(cfg.model || ""),
        quick_model: String(cfg.quick_model || ""),
        deep_model: String(cfg.deep_model || ""),
        timeout_s: Number(cfg.timeout_s || prev.timeout_s || 120),
        max_tokens: Number(cfg.max_tokens || prev.max_tokens || 4096),
        temperature: Number(cfg.temperature || prev.temperature || 0.7),
      }));
      setErr("");
    } catch (error) {
      const text = error instanceof ApiClientError ? `${error.code}: ${error.message}` : "系统数据加载失败";
      setErr(text);
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => {
      void load();
    }, 5000);
    return () => window.clearInterval(timer);
  }, [load]);

  const saveLlmConfig = async () => {
    setWorking(true);
    setMsg("");
    setErr("");
    try {
      const payload = await api.put<Record<string, unknown>>("/api/system/llm/config", {
        provider_name: llmForm.provider_name.trim(),
        base_url: llmForm.base_url.trim(),
        model: llmForm.model.trim(),
        quick_model: llmForm.quick_model.trim(),
        deep_model: llmForm.deep_model.trim(),
        timeout_s: Number(llmForm.timeout_s),
        max_tokens: Number(llmForm.max_tokens),
        temperature: Number(llmForm.temperature),
        api_key: llmForm.api_key.trim(),
      });
      setMsg(`LLM 配置已保存: ${dump(payload)}`);
      setLlmForm((prev) => ({ ...prev, api_key: "" }));
      await load();
    } catch (error) {
      const text = error instanceof ApiClientError ? `${error.code}: ${error.message}` : "保存失败";
      setErr(text);
    } finally {
      setWorking(false);
    }
  };

  const testLlmConfig = async () => {
    setWorking(true);
    setMsg("");
    setErr("");
    try {
      const payload = await api.post<Record<string, unknown>>("/api/system/llm/config/test", {
        provider_name: llmForm.provider_name.trim(),
        base_url: llmForm.base_url.trim(),
        model: llmForm.model.trim(),
        quick_model: llmForm.quick_model.trim(),
        deep_model: llmForm.deep_model.trim(),
        timeout_s: Number(llmForm.timeout_s),
        max_tokens: Number(llmForm.max_tokens),
        temperature: Number(llmForm.temperature),
        api_key: llmForm.api_key.trim(),
      });
      setMsg(`LLM 连通性测试成功: ${dump(payload)}`);
    } catch (error) {
      const text = error instanceof ApiClientError ? `${error.code}: ${error.message}` : "测试失败";
      setErr(text);
    } finally {
      setWorking(false);
    }
  };

  const startBridge = async () => {
    setWorking(true);
    setMsg("");
    setErr("");
    try {
      const payload = await api.post<Record<string, unknown>>("/api/system/ths-bridge/start", {
        channel: "ths_ipc",
        restart: true,
        allow_disabled: true,
      });
      setMsg(`THS bridge 已启动: ${dump(payload)}`);
      await load();
    } catch (error) {
      const text = error instanceof ApiClientError ? `${error.code}: ${error.message}` : "启动失败";
      setErr(text);
    } finally {
      setWorking(false);
    }
  };

  const stopBridge = async () => {
    setWorking(true);
    setMsg("");
    setErr("");
    try {
      const payload = await api.post<Record<string, unknown>>("/api/system/ths-bridge/stop", {
        force: true,
        reason: "frontend_stop",
      });
      setMsg(`THS bridge 已停止: ${dump(payload)}`);
      await load();
    } catch (error) {
      const text = error instanceof ApiClientError ? `${error.code}: ${error.message}` : "停止失败";
      setErr(text);
    } finally {
      setWorking(false);
    }
  };

  const applyProfile = async (profile: string) => {
    setWorking(true);
    setMsg("");
    setErr("");
    try {
      const payload = await api.post<Record<string, unknown>>("/api/system/dataflow/profile/apply", {
        profile,
        persist: true,
      });
      setMsg(`profile 已应用: ${dump(payload)}`);
      await load();
    } catch (error) {
      const text = error instanceof ApiClientError ? `${error.code}: ${error.message}` : "应用 profile 失败";
      setErr(text);
    } finally {
      setWorking(false);
    }
  };

  const profileNames = Object.keys((profiles?.profiles as Record<string, unknown>) || {});

  return (
    <CyberpunkLayout pageTitle="SYSTEM_TERMINAL">
      {msg ? <p className="msg-ok">{msg}</p> : null}
      {err ? <p className="msg-error">{err}</p> : null}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "24px", marginBottom: "24px" }}>
        <article className="cyber-card cyan">
          <h4 style={{ color: "var(--color-cyan)", marginBottom: "16px", fontSize: "12px", letterSpacing: "2px" }}>LLM_CONFIG_MATRIX</h4>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
            <div className="form-field">
              <label style={{ fontSize: "10px", color: "var(--color-text-soft)" }}>Provider</label>
              <input style={{ background: "rgba(0,0,0,0.3)", border: "1px solid rgba(0,240,255,0.2)", color: "#fff", padding: "6px" }} value={llmForm.provider_name} onChange={(e) => setLlmForm((prev) => ({ ...prev, provider_name: e.target.value }))} />
            </div>
            <div className="form-field">
              <label style={{ fontSize: "10px", color: "var(--color-text-soft)" }}>Model</label>
              <input style={{ background: "rgba(0,0,0,0.3)", border: "1px solid rgba(0,240,255,0.2)", color: "#fff", padding: "6px" }} value={llmForm.model} onChange={(e) => setLlmForm((prev) => ({ ...prev, model: e.target.value }))} />
            </div>
          </div>
          <div className="form-field" style={{ marginTop: "10px" }}>
            <label style={{ fontSize: "10px", color: "var(--color-text-soft)" }}>Base URL</label>
            <input style={{ width: "100%", background: "rgba(0,0,0,0.3)", border: "1px solid rgba(0,240,255,0.2)", color: "#fff", padding: "6px" }} value={llmForm.base_url} onChange={(e) => setLlmForm((prev) => ({ ...prev, base_url: e.target.value }))} />
          </div>
          <div className="form-field" style={{ marginTop: "10px" }}>
            <label style={{ fontSize: "10px", color: "var(--color-text-soft)" }}>API Key</label>
            <input type="password" style={{ width: "100%", background: "rgba(0,0,0,0.3)", border: "1px solid rgba(0,240,255,0.2)", color: "#fff", padding: "6px" }} value={llmForm.api_key} onChange={(e) => setLlmForm((prev) => ({ ...prev, api_key: e.target.value }))} />
          </div>
          <div style={{ display: "flex", gap: "10px", marginTop: "16px" }}>
            <button className="cyber-card cyan" style={{ flex: 1, padding: "10px", background: "var(--color-cyan)", color: "#000", border: "none", fontWeight: 700 }} onClick={() => void saveLlmConfig()} disabled={working}>SAVE</button>
            <button className="cyber-card" style={{ flex: 1, padding: "10px", background: "transparent", color: "var(--color-cyan)", border: "1px solid var(--color-cyan)" }} onClick={() => void testLlmConfig()} disabled={working}>TEST</button>
          </div>
        </article>

        <article className="cyber-card yellow">
          <h4 style={{ color: "var(--color-yellow)", marginBottom: "16px", fontSize: "12px", letterSpacing: "2px" }}>BRIDGE_&_PREFLIGHT</h4>
          <div style={{ display: "flex", gap: "10px", marginBottom: "16px" }}>
            <button className="cyber-card green" style={{ flex: 1, padding: "8px", background: "var(--color-green)", color: "#000", border: "none", fontWeight: 700 }} onClick={() => void startBridge()} disabled={working}>START_BRIDGE</button>
            <button className="cyber-card red" style={{ flex: 1, padding: "8px", background: "var(--color-red)", color: "#fff", border: "none", fontWeight: 700 }} onClick={() => void stopBridge()} disabled={working}>STOP_BRIDGE</button>
          </div>
          <pre style={{ fontSize: "10px", background: "rgba(0,0,0,0.5)", padding: "8px", color: "var(--color-text-soft)", maxHeight: "150px", overflow: "auto" }}>
            {dump(bridge || {})}
          </pre>
        </article>
      </div>

      <div className="cyber-card magenta" style={{ marginBottom: "24px" }}>
        <h4 style={{ color: "var(--color-magenta)", marginBottom: "16px", fontSize: "12px", letterSpacing: "2px" }}>DATAFLOW_PROFILES</h4>
        <div style={{ display: "flex", gap: "10px", marginBottom: "16px", flexWrap: "wrap" }}>
          {profileNames.map((name) => (
            <button key={name} className="cyber-card magenta" style={{ padding: "8px 16px", background: "transparent", color: "var(--color-magenta)", border: "1px solid var(--color-magenta)", fontSize: "11px", fontWeight: 700 }} onClick={() => void applyProfile(name)} disabled={working}>
              APPLY_{name.toUpperCase()}
            </button>
          ))}
        </div>
        <pre style={{ fontSize: "10px", background: "rgba(0,0,0,0.5)", padding: "8px", color: "var(--color-text-soft)", maxHeight: "200px", overflow: "auto" }}>
          {dump(profiles || {})}
        </pre>
      </div>
    </CyberpunkLayout>
  );
}
