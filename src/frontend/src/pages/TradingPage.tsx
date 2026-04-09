import { useCallback, useEffect, useMemo, useState } from "react";
import { CyberpunkLayout } from "../components/CyberpunkLayout";
import { ApiClientError, api } from "../services/api";

interface DirectOrderForm {
  ticker: string;
  side: "BUY" | "SELL";
  qty: number;
  price: number;
  type: "limit" | "market";
  idempotency_key: string;
  client_order_id: string;
  channel: string;
  manual_confirm: boolean;
  manual_confirm_token: string;
  memo: string;
}

function makeIdempotencyKey() {
  return `idem-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
}

function toDisplayJson(value: unknown) {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export function TradingPage() {
  const [form, setForm] = useState<DirectOrderForm>({
    ticker: "000001",
    side: "BUY",
    qty: 100,
    price: 10,
    type: "limit",
    idempotency_key: makeIdempotencyKey(),
    client_order_id: "",
    channel: "",
    manual_confirm: false,
    manual_confirm_token: "",
    memo: "",
  });
  const [submitting, setSubmitting] = useState(false);
  const [submitMsg, setSubmitMsg] = useState<string>("");
  const [submitErr, setSubmitErr] = useState<string>("");
  const [submitPayload, setSubmitPayload] = useState<Record<string, unknown> | null>(null);

  const [balance, setBalance] = useState<Record<string, unknown> | null>(null);
  const [positions, setPositions] = useState<Record<string, unknown>[]>([]);
  const [activeOrders, setActiveOrders] = useState<Record<string, unknown>[]>([]);
  const [syncMsg, setSyncMsg] = useState("");

  const [traceQueryType, setTraceQueryType] = useState<"idempotency_key" | "trace_id" | "client_order_id">("idempotency_key");
  const [traceQueryValue, setTraceQueryValue] = useState("");
  const [tracePayload, setTracePayload] = useState<Record<string, unknown> | null>(null);
  const [traceErr, setTraceErr] = useState("");

  const loadSnapshot = useCallback(async () => {
    try {
      const [balancePayload, positionsPayload, ordersPayload] = await Promise.all([
        api.get<Record<string, unknown>>("/api/trading/balance"),
        api.get<Record<string, unknown>[]>("/api/trading/positions"),
        api.get<Record<string, unknown>[]>("/api/trading/orders/active"),
      ]);
      setBalance(balancePayload);
      setPositions(Array.isArray(positionsPayload) ? positionsPayload : []);
      setActiveOrders(Array.isArray(ordersPayload) ? ordersPayload : []);
    } catch {
      // keep previous state, explicit failure displayed by user actions only
    }
  }, []);

  useEffect(() => {
    void loadSnapshot();
    const timer = window.setInterval(() => {
      void loadSnapshot();
    }, 5000);
    return () => window.clearInterval(timer);
  }, [loadSnapshot]);

  const onSubmit = async () => {
    setSubmitting(true);
    setSubmitMsg("");
    setSubmitErr("");
    setSubmitPayload(null);
    try {
      const payload = await api.post<Record<string, unknown>>("/api/trading/orders/direct", {
        ticker: form.ticker.trim(),
        side: form.side,
        qty: Number(form.qty),
        price: Number(form.price),
        type: form.type,
        idempotency_key: form.idempotency_key.trim(),
        client_order_id: form.client_order_id.trim(),
        channel: form.channel.trim(),
        memo: form.memo,
        manual_confirm: form.manual_confirm,
        manual_confirm_token: form.manual_confirm_token.trim(),
      });
      setSubmitPayload(payload);
      setSubmitMsg("下单请求已受理");
      setTraceQueryType("idempotency_key");
      setTraceQueryValue(form.idempotency_key.trim());
      setForm((prev) => ({ ...prev, idempotency_key: makeIdempotencyKey() }));
      await loadSnapshot();
    } catch (error) {
      const msg =
        error instanceof ApiClientError
          ? `${error.code}: ${error.message}`
          : error instanceof Error
            ? error.message
            : "下单失败";
      setSubmitErr(msg);
    } finally {
      setSubmitting(false);
    }
  };

  const onSyncOrders = async () => {
    setSyncMsg("");
    try {
      const payload = await api.post<Record<string, unknown>>("/api/trading/orders/sync", {});
      setSyncMsg(`同步完成：${toDisplayJson(payload)}`);
      await loadSnapshot();
    } catch (error) {
      const msg = error instanceof ApiClientError ? `${error.code}: ${error.message}` : "订单同步失败";
      setSyncMsg(msg);
    }
  };

  const onQueryTrace = async () => {
    setTraceErr("");
    setTracePayload(null);
    if (!traceQueryValue.trim()) {
      setTraceErr("请输入查询值");
      return;
    }

    try {
      const query: Record<string, string> = { [traceQueryType]: traceQueryValue.trim() };
      const payload = await api.get<Record<string, unknown>>("/api/trading/orders/trace", query);
      setTracePayload(payload);
    } catch (error) {
      const msg =
        error instanceof ApiClientError
          ? `${error.code}: ${error.message}`
          : error instanceof Error
            ? error.message
            : "查询失败";
      setTraceErr(msg);
    }
  };

  const orderRows = useMemo(() => activeOrders.slice(0, 50), [activeOrders]);

  return (
    <CyberpunkLayout pageTitle="TRADING_CENTER">
      {submitMsg ? <p className="msg-ok">{submitMsg}</p> : null}
      {submitErr ? <p className="msg-error">{submitErr}</p> : null}
      {syncMsg ? <p className="msg-info">{syncMsg}</p> : null}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "24px", marginBottom: "24px" }}>
        <article className="cyber-card cyan">
          <h4 style={{ color: "var(--color-cyan)", marginBottom: "16px", fontSize: "12px", letterSpacing: "2px" }}>DIRECT_ORDER_FORM</h4>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
            <div className="form-field">
              <label style={{ fontSize: "10px", color: "var(--color-text-soft)" }}>Ticker</label>
              <input style={{ background: "rgba(0,0,0,0.3)", border: "1px solid rgba(0,240,255,0.2)", color: "#fff", padding: "8px" }} value={form.ticker} onChange={(e) => setForm((prev) => ({ ...prev, ticker: e.target.value }))} />
            </div>
            <div className="form-field">
              <label style={{ fontSize: "10px", color: "var(--color-text-soft)" }}>Side</label>
              <select style={{ background: "rgba(0,0,0,0.3)", border: "1px solid rgba(0,240,255,0.2)", color: "#fff", padding: "8px" }} value={form.side} onChange={(e) => setForm((prev) => ({ ...prev, side: e.target.value as "BUY" | "SELL" }))}>
                <option value="BUY">BUY</option>
                <option value="SELL">SELL</option>
              </select>
            </div>
            <div className="form-field">
              <label style={{ fontSize: "10px", color: "var(--color-text-soft)" }}>Qty</label>
              <input style={{ background: "rgba(0,0,0,0.3)", border: "1px solid rgba(0,240,255,0.2)", color: "#fff", padding: "8px" }} type="number" value={form.qty} onChange={(e) => setForm((prev) => ({ ...prev, qty: Number(e.target.value) || 0 }))} />
            </div>
            <div className="form-field">
              <label style={{ fontSize: "10px", color: "var(--color-text-soft)" }}>Price</label>
              <input style={{ background: "rgba(0,0,0,0.3)", border: "1px solid rgba(0,240,255,0.2)", color: "#fff", padding: "8px" }} type="number" value={form.price} onChange={(e) => setForm((prev) => ({ ...prev, price: Number(e.target.value) || 0 }))} />
            </div>
          </div>
          <div style={{ marginTop: "16px", display: "flex", gap: "10px" }}>
            <button className="cyber-card" style={{ flex: 1, padding: "10px", background: "var(--color-cyan)", color: "#000", fontWeight: 700, border: "none" }} onClick={() => void onSubmit()} disabled={submitting}>
              {submitting ? "SUBMITTING..." : "EXECUTE_TRADE"}
            </button>
            <button className="cyber-card" style={{ padding: "10px", background: "transparent", color: "var(--color-cyan)", border: "1px solid var(--color-cyan)" }} onClick={onSyncOrders}>
              SYNC
            </button>
          </div>
        </article>

        <article className="cyber-card magenta">
          <h4 style={{ color: "var(--color-magenta)", marginBottom: "16px", fontSize: "12px", letterSpacing: "2px" }}>ORDER_TRACE</h4>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px", marginBottom: "12px" }}>
            <select style={{ background: "rgba(0,0,0,0.3)", border: "1px solid rgba(255,0,170,0.2)", color: "#fff", padding: "8px" }} value={traceQueryType} onChange={(e) => setTraceQueryType(e.target.value as typeof traceQueryType)}>
              <option value="idempotency_key">IDEM_KEY</option>
              <option value="trace_id">TRACE_ID</option>
              <option value="client_order_id">CLIENT_ID</option>
            </select>
            <input style={{ background: "rgba(0,0,0,0.3)", border: "1px solid rgba(255,0,170,0.2)", color: "#fff", padding: "8px" }} value={traceQueryValue} onChange={(e) => setTraceQueryValue(e.target.value)} placeholder="Value..." />
          </div>
          <button className="cyber-card" style={{ width: "100%", padding: "10px", background: "var(--color-magenta)", color: "#fff", fontWeight: 700, border: "none" }} onClick={() => void onQueryTrace()}>
            QUERY_TRACE_LOG
          </button>
          {tracePayload && (
            <pre style={{ marginTop: "12px", fontSize: "10px", color: "var(--color-text-soft)", background: "rgba(0,0,0,0.5)", padding: "8px", maxHeight: "100px", overflow: "auto" }}>
              {toDisplayJson(tracePayload)}
            </pre>
          )}
        </article>
      </div>

      <div className="cyber-card" style={{ marginBottom: "24px" }}>
        <h4 style={{ color: "var(--color-cyan)", marginBottom: "16px", fontSize: "12px", letterSpacing: "2px" }}>ACTIVE_ORDERS_HUD</h4>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px", fontFamily: "var(--font-mono)" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid rgba(0,240,255,0.2)", color: "var(--color-text-soft)", textAlign: "left" }}>
                <th style={{ padding: "12px" }}>ID</th>
                <th style={{ padding: "12px" }}>TICKER</th>
                <th style={{ padding: "12px" }}>SIDE</th>
                <th style={{ padding: "12px" }}>QTY</th>
                <th style={{ padding: "12px" }}>PRICE</th>
                <th style={{ padding: "12px" }}>STATUS</th>
              </tr>
            </thead>
            <tbody>
              {orderRows.map((row, idx) => (
                <tr key={idx} style={{ borderBottom: "1px solid rgba(255,255,255,0.05)", color: "#fff" }}>
                  <td style={{ padding: "12px" }}>{String(row.order_id).slice(-8)}</td>
                  <td style={{ padding: "12px" }}>{String(row.ticker)}</td>
                  <td style={{ padding: "12px", color: row.side === "BUY" ? "var(--color-green)" : "var(--color-red)" }}>{String(row.side)}</td>
                  <td style={{ padding: "12px" }}>{String(row.quantity)}</td>
                  <td style={{ padding: "12px" }}>{String(row.price)}</td>
                  <td style={{ padding: "12px" }}>
                    <span style={{ 
                      padding: "2px 6px", 
                      background: "rgba(0,240,255,0.1)", 
                      border: "1px solid var(--color-cyan)",
                      fontSize: "10px"
                    }}>
                      {String(row.status)}
                    </span>
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
