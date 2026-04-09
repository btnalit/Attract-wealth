import { useCallback, useEffect, useMemo, useState } from "react";
import { CyberpunkLayout } from "../components/CyberpunkLayout";
import { ApiClientError, api } from "../services/api";

function nowTag() {
  return new Date().toISOString().replace(/[.:]/g, "-");
}

function sampleBars() {
  const closes = [10.0, 10.2, 10.15, 10.35, 10.1, 10.45, 10.52, 10.4, 10.6, 10.7];
  return closes.map((close, idx) => ({
    ts: `2026-01-${String(idx + 1).padStart(2, "0")}`,
    close,
    signal: "AUTO",
  }));
}

function display(value: unknown) {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export function StrategyPage() {
  const [items, setItems] = useState<Record<string, unknown>[]>([]);
  const [reports, setReports] = useState<Record<string, unknown>[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [statusTarget, setStatusTarget] = useState("candidate");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [working, setWorking] = useState(false);

  const [newName, setNewName] = useState("demo_strategy");
  const [newTemplate, setNewTemplate] = useState("default");
  const [newMarket, setNewMarket] = useState("CN");

  const load = useCallback(async () => {
    try {
      const [versionPayload, reportPayload] = await Promise.all([
        api.get<{ items: Record<string, unknown>[] }>("/api/strategy/versions", { limit: 100 }),
        api.get<{ items: Record<string, unknown>[] }>("/api/strategy/backtests", { limit: 100 }),
      ]);
      const strategyItems = versionPayload.items || [];
      setItems(strategyItems);
      setReports(reportPayload.items || []);
      if (!selectedId && strategyItems.length > 0) {
        setSelectedId(String(strategyItems[0].id || ""));
      }
      setError("");
    } catch (err) {
      const msg = err instanceof ApiClientError ? `${err.code}: ${err.message}` : "加载策略数据失败";
      setError(msg);
    }
  }, [selectedId]);

  useEffect(() => {
    void load();
  }, [load]);

  const selected = useMemo(
    () => items.find((item) => String(item.id || "") === selectedId) || null,
    [items, selectedId]
  );

  const createStrategy = async () => {
    if (!newName.trim()) {
      setError("策略名不能为空");
      return;
    }

    setWorking(true);
    setMessage("");
    setError("");
    try {
      const payload = await api.post<Record<string, unknown>>("/api/strategy/versions", {
        name: newName.trim(),
        status: "draft",
        market: newMarket,
        strategy_template: newTemplate,
        content: "# strategy definition\nrule: momentum",
        parameters: {
          window: 5,
          threshold: 0.5,
          strategy_template: newTemplate,
        },
      });
      setMessage(`已创建策略版本: ${display(payload)}`);
      await load();
    } catch (err) {
      const msg = err instanceof ApiClientError ? `${err.code}: ${err.message}` : "创建策略失败";
      setError(msg);
    } finally {
      setWorking(false);
    }
  };

  const runBacktest = async (grid: boolean) => {
    if (!selectedId) {
      setError("请先选择策略版本");
      return;
    }

    setWorking(true);
    setMessage("");
    setError("");
    try {
      const runTag = `frontend-${grid ? "grid" : "single"}-${nowTag()}`;
      const body = grid
        ? {
            strategy_id: selectedId,
            bars: sampleBars(),
            market: String(selected?.market || "CN"),
            strategy_template: String(selected?.strategy_template || "default"),
            run_tag: runTag,
            parameter_grid: {
              window: [3, 5, 8],
              threshold: [0.3, 0.5],
            },
            max_combinations: 12,
          }
        : {
            strategy_id: selectedId,
            bars: sampleBars(),
            market: String(selected?.market || "CN"),
            strategy_template: String(selected?.strategy_template || "default"),
            run_tag: runTag,
          };
      const payload = await api.post<Record<string, unknown>>(
        grid ? "/api/strategy/backtest/grid" : "/api/strategy/backtest",
        body
      );
      setMessage(`回测完成: ${display(payload)}`);
      await load();
    } catch (err) {
      const msg = err instanceof ApiClientError ? `${err.code}: ${err.message}` : "回测失败";
      setError(msg);
    } finally {
      setWorking(false);
    }
  };

  const runGate = async () => {
    if (!selectedId) {
      setError("请先选择策略版本");
      return;
    }
    setWorking(true);
    setMessage("");
    setError("");
    try {
      const payload = await api.post<Record<string, unknown>>(`/api/strategy/versions/${selectedId}/gate`, {
        persist: true,
        market: String(selected?.market || "CN"),
        strategy_template: String(selected?.strategy_template || "default"),
      });
      setMessage(`门禁评估完成: ${display(payload)}`);
      await load();
    } catch (err) {
      const msg = err instanceof ApiClientError ? `${err.code}: ${err.message}` : "门禁评估失败";
      setError(msg);
    } finally {
      setWorking(false);
    }
  };

  const transitionStatus = async () => {
    if (!selectedId) {
      setError("请先选择策略版本");
      return;
    }
    setWorking(true);
    setMessage("");
    setError("");
    try {
      const payload = await api.post<Record<string, unknown>>(`/api/strategy/versions/${selectedId}/transition`, {
        target_status: statusTarget,
        operator: "frontend",
        strategy_template: String(selected?.strategy_template || "default"),
        market: String(selected?.market || "CN"),
      });
      setMessage(`状态迁移完成: ${display(payload)}`);
      await load();
    } catch (err) {
      const msg = err instanceof ApiClientError ? `${err.code}: ${err.message}` : "状态迁移失败";
      setError(msg);
    } finally {
      setWorking(false);
    }
  };

  const promote = async () => {
    if (!selectedId) {
      setError("请先选择策略版本");
      return;
    }

    setWorking(true);
    setMessage("");
    setError("");
    try {
      const payload = await api.post<Record<string, unknown>>(`/api/strategy/versions/${selectedId}/promote`, {
        operator: "frontend",
        run_gate: true,
        force: false,
        strategy_template: String(selected?.strategy_template || "default"),
        market: String(selected?.market || "CN"),
      });
      setMessage(`版本晋升完成: ${display(payload)}`);
      await load();
    } catch (err) {
      const msg = err instanceof ApiClientError ? `${err.code}: ${err.message}` : "版本晋升失败";
      setError(msg);
    } finally {
      setWorking(false);
    }
  };

  return (
    <CyberpunkLayout pageTitle="STRATEGY_FORGE">
      {message ? <p className="msg-ok">{message}</p> : null}
      {error ? <p className="msg-error">{error}</p> : null}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "24px", marginBottom: "24px" }}>
        <article className="cyber-card magenta">
          <h4 style={{ color: "var(--color-magenta)", marginBottom: "16px", fontSize: "12px", letterSpacing: "2px" }}>VERSION_CREATION</h4>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
            <div className="form-field">
              <label style={{ fontSize: "10px", color: "var(--color-text-soft)" }}>Strategy Name</label>
              <input style={{ background: "rgba(0,0,0,0.3)", border: "1px solid rgba(255,0,170,0.2)", color: "#fff", padding: "8px" }} value={newName} onChange={(e) => setNewName(e.target.value)} />
            </div>
            <div className="form-field">
              <label style={{ fontSize: "10px", color: "var(--color-text-soft)" }}>Template</label>
              <input style={{ background: "rgba(0,0,0,0.3)", border: "1px solid rgba(255,0,170,0.2)", color: "#fff", padding: "8px" }} value={newTemplate} onChange={(e) => setNewTemplate(e.target.value)} />
            </div>
          </div>
          <button className="cyber-card" style={{ width: "100%", padding: "10px", background: "var(--color-magenta)", color: "#fff", fontWeight: 700, border: "none", marginTop: "16px" }} onClick={() => void createStrategy()} disabled={working}>
            FORGE_VERSION
          </button>
        </article>

        <article className="cyber-card yellow">
          <h4 style={{ color: "var(--color-yellow)", marginBottom: "16px", fontSize: "12px", letterSpacing: "2px" }}>LIFECYCLE_&_GATES</h4>
          <div className="form-field">
            <label style={{ fontSize: "10px", color: "var(--color-text-soft)" }}>Target Status</label>
            <select style={{ width: "100%", background: "rgba(0,0,0,0.3)", border: "1px solid rgba(255,230,0,0.2)", color: "#fff", padding: "8px" }} value={statusTarget} onChange={(e) => setStatusTarget(e.target.value)}>
              <option value="candidate">candidate</option>
              <option value="active">active</option>
              <option value="retired">retired</option>
              <option value="rejected">rejected</option>
            </select>
          </div>
          <div style={{ display: "flex", gap: "10px", marginTop: "16px" }}>
            <button className="cyber-card yellow" style={{ flex: 1, padding: "10px", background: "transparent", color: "var(--color-yellow)", border: "1px solid var(--color-yellow)", fontSize: "11px" }} onClick={() => void runGate()} disabled={working || !selectedId}>EVAL_GATE</button>
            <button className="cyber-card yellow" style={{ flex: 1, padding: "10px", background: "var(--color-yellow)", color: "#000", border: "none", fontWeight: 700, fontSize: "11px" }} onClick={() => void promote()} disabled={working || !selectedId}>PROMOTE</button>
          </div>
        </article>
      </div>

      <div className="cyber-card cyan" style={{ marginBottom: "24px" }}>
        <h4 style={{ color: "var(--color-cyan)", marginBottom: "16px", fontSize: "12px", letterSpacing: "2px" }}>STRATEGY_REGISTRY</h4>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "11px", fontFamily: "var(--font-mono)" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid rgba(0,240,255,0.2)", color: "var(--color-text-soft)", textAlign: "left" }}>
                <th style={{ padding: "10px" }}>ID</th>
                <th style={{ padding: "10px" }}>NAME</th>
                <th style={{ padding: "10px" }}>VER</th>
                <th style={{ padding: "10px" }}>STATUS</th>
                <th style={{ padding: "10px" }}>ACTION</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item, idx) => (
                <tr key={idx} style={{ borderBottom: "1px solid rgba(255,255,255,0.05)", color: "#fff" }}>
                  <td style={{ padding: "10px" }}>{String(item.id).slice(-6)}</td>
                  <td style={{ padding: "10px" }}>{String(item.name)}</td>
                  <td style={{ padding: "10px" }}>{String(item.version)}</td>
                  <td style={{ padding: "10px" }}>
                    <span style={{ 
                      padding: "2px 6px", 
                      background: "rgba(0,240,255,0.1)", 
                      border: "1px solid var(--color-cyan)",
                      fontSize: "9px"
                    }}>{String(item.status)}</span>
                  </td>
                  <td style={{ padding: "10px" }}>
                    <button style={{ color: "var(--color-cyan)", background: "transparent", border: "none", cursor: "pointer", fontSize: "10px", textDecoration: "underline" }} onClick={() => setSelectedId(String(item.id))}>SELECT</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </CyberpunkLayout>
  );
}
