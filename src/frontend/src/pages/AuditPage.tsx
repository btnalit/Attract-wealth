import { useCallback, useEffect, useState } from "react";
import { CyberpunkLayout } from "../components/CyberpunkLayout";
import { ApiClientError, api } from "../services/api";

function json(value: unknown) {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export function AuditPage() {
  const [evidence, setEvidence] = useState<Record<string, unknown>[]>([]);
  const [guard, setGuard] = useState<Record<string, unknown> | null>(null);
  const [errorCodes, setErrorCodes] = useState<Record<string, unknown>[]>([]);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [unlockToken, setUnlockToken] = useState("");

  const load = useCallback(async () => {
    try {
      const [evidencePayload, guardPayload, errorCodePayload] = await Promise.all([
        api.get<{ items: Record<string, unknown>[] }>("/api/system/audit/evidence", { limit: 60 }),
        api.get<Record<string, unknown>>("/api/system/reconciliation/guard"),
        api.get<{ items: Record<string, unknown>[] }>("/api/system/error-codes"),
      ]);
      setEvidence(evidencePayload.items || []);
      setGuard(guardPayload);
      setErrorCodes(errorCodePayload.items || []);
      setError("");
    } catch (err) {
      const msg = err instanceof ApiClientError ? `${err.code}: ${err.message}` : "加载审计数据失败";
      setError(msg);
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => {
      void load();
    }, 5000);
    return () => window.clearInterval(timer);
  }, [load]);

  const reconcile = async () => {
    setMessage("");
    setError("");
    try {
      const payload = await api.post<Record<string, unknown>>("/api/trading/reconcile", {});
      setMessage(`对账完成: ${json(payload)}`);
      await load();
    } catch (err) {
      const msg = err instanceof ApiClientError ? `${err.code}: ${err.message}` : "对账失败";
      setError(msg);
    }
  };

  const unlock = async () => {
    setMessage("");
    setError("");
    try {
      const headers = unlockToken.trim() ? { "X-Recon-Unlock-Token": unlockToken.trim() } : undefined;
      const payload = await api.post<Record<string, unknown>>(
        "/api/trading/reconcile/unlock",
        { reason: "frontend_manual_unlock", operator: "frontend" },
        headers
      );
      setMessage(`手动解锁完成: ${json(payload)}`);
      await load();
    } catch (err) {
      const msg = err instanceof ApiClientError ? `${err.code}: ${err.message}` : "解锁失败";
      setError(msg);
    }
  };

  return (
    <CyberpunkLayout pageTitle="AUDIT_&_SECURITY">
      {message ? <p className="msg-ok">{message}</p> : null}
      {error ? <p className="msg-error">{error}</p> : null}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "24px", marginBottom: "24px" }}>
        <article className="cyber-card yellow">
          <h4 style={{ color: "var(--color-yellow)", marginBottom: "16px", fontSize: "12px", letterSpacing: "2px" }}>RECONCILIATION_GUARD</h4>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "12px" }}>
            <span>SYSTEM_STATUS:</span>
            <span style={{ 
              color: guard?.blocked ? "var(--color-red)" : "var(--color-green)", 
              fontWeight: 800,
              textShadow: guard?.blocked ? "0 0 5px var(--color-red)" : "0 0 5px var(--color-green)"
            }}>
              {guard?.blocked ? "BLOCKED" : "OPERATIONAL"}
            </span>
          </div>
          <pre style={{ 
            whiteSpace: "pre-wrap", 
            fontSize: "10px", 
            color: "var(--color-text-soft)",
            background: "rgba(0,0,0,0.5)",
            padding: "8px",
            maxHeight: "150px",
            overflow: "auto"
          }}>
            {json(guard || {})}
          </pre>
          <div style={{ marginTop: "16px" }}>
            <label style={{ fontSize: "10px", color: "var(--color-text-soft)" }}>UNLOCK_TOKEN</label>
            <input 
              style={{ width: "100%", background: "rgba(0,0,0,0.3)", border: "1px solid rgba(255,230,0,0.2)", color: "#fff", padding: "8px", marginTop: "4px" }} 
              value={unlockToken} onChange={(e) => setUnlockToken(e.target.value)} 
            />
          </div>
          <div style={{ display: "flex", gap: "10px", marginTop: "16px" }}>
            <button className="cyber-card red" style={{ flex: 1, padding: "10px", background: "var(--color-red)", color: "#fff", border: "none", fontWeight: 700 }} onClick={() => void unlock()}>
              FORCE_UNLOCK
            </button>
            <button className="cyber-card yellow" style={{ flex: 1, padding: "10px", background: "transparent", color: "var(--color-yellow)", border: "1px solid var(--color-yellow)" }} onClick={() => void reconcile()}>
              RECONCILE
            </button>
          </div>
        </article>

        <article className="cyber-card cyan">
          <h4 style={{ color: "var(--color-cyan)", marginBottom: "16px", fontSize: "12px", letterSpacing: "2px" }}>ERROR_DICTIONARY</h4>
          <div style={{ overflowY: "auto", maxHeight: "300px" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "11px", fontFamily: "var(--font-mono)" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid rgba(0,240,255,0.2)", color: "var(--color-text-soft)", textAlign: "left" }}>
                  <th style={{ padding: "8px" }}>CODE</th>
                  <th style={{ padding: "8px" }}>CATEGORY</th>
                  <th style={{ padding: "8px" }}>RETRY</th>
                </tr>
              </thead>
              <tbody>
                {errorCodes.map((row, idx) => (
                  <tr key={idx} style={{ borderBottom: "1px solid rgba(255,255,255,0.05)", color: "#fff" }}>
                    <td style={{ padding: "8px" }}>{String(row.code)}</td>
                    <td style={{ padding: "8px" }}>{String(row.category)}</td>
                    <td style={{ padding: "8px", color: row.retryable ? "var(--color-green)" : "var(--color-red)" }}>{String(row.retryable)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>
      </div>

      <div className="cyber-card magenta" style={{ marginBottom: "24px" }}>
        <h4 style={{ color: "var(--color-magenta)", marginBottom: "16px", fontSize: "12px", letterSpacing: "2px" }}>EVIDENCE_CHAIN_TIMELINE</h4>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "11px", fontFamily: "var(--font-mono)" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid rgba(255,0,170,0.2)", color: "var(--color-text-soft)", textAlign: "left" }}>
                <th style={{ padding: "12px" }}>TIMESTAMP</th>
                <th style={{ padding: "12px" }}>PHASE</th>
                <th style={{ padding: "12px" }}>TICKER</th>
                <th style={{ padding: "12px" }}>DECISION</th>
                <th style={{ padding: "12px" }}>TRACE_ID</th>
              </tr>
            </thead>
            <tbody>
              {evidence.map((row, idx) => {
                const trace = (row.trace as Record<string, unknown>) || {};
                return (
                  <tr key={idx} style={{ borderBottom: "1px solid rgba(255,255,255,0.05)", color: "#fff" }}>
                    <td style={{ padding: "12px" }}>{String(row.timestamp).slice(11, 19)}</td>
                    <td style={{ padding: "12px" }}>
                      <span style={{ 
                        padding: "1px 4px", 
                        background: "rgba(255,0,170,0.1)", 
                        border: "1px solid var(--color-magenta)",
                        fontSize: "9px"
                      }}>{String(row.phase)}</span>
                    </td>
                    <td style={{ padding: "12px" }}>{String(row.ticker)}</td>
                    <td style={{ padding: "12px", color: row.decision === "BUY" ? "var(--color-green)" : row.decision === "SELL" ? "var(--color-red)" : "#fff" }}>{String(row.decision)}</td>
                    <td style={{ padding: "12px", color: "var(--color-cyan)" }}>{String(trace.trace_id).slice(-8)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </CyberpunkLayout>
  );
}
