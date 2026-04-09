import React, { useMemo, useCallback } from "react";
import { ReactFlow, Background, Controls, Edge, Node, Position, MarkerType } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { CyberpunkLayout } from "../components/CyberpunkLayout";

const initialNodes: Node[] = [
  {
    id: "collector",
    position: { x: 50, y: 150 },
    data: { label: "Data Collector" },
    style: { borderColor: "var(--color-cyan)", borderLeftWidth: "4px" },
    sourcePosition: Position.Right,
  },
  {
    id: "analysts",
    position: { x: 250, y: 150 },
    data: { label: "Market Analysts" },
    style: { borderColor: "var(--color-yellow)", borderLeftWidth: "4px" },
    sourcePosition: Position.Right,
    targetPosition: Position.Left,
  },
  {
    id: "debate",
    position: { x: 450, y: 150 },
    data: { label: "Debate Engine" },
    style: { borderColor: "var(--color-magenta)", borderLeftWidth: "4px" },
    sourcePosition: Position.Right,
    targetPosition: Position.Left,
  },
  {
    id: "trader",
    position: { x: 650, y: 150 },
    data: { label: "Trader Agent" },
    style: { borderColor: "var(--color-cyan)", borderLeftWidth: "4px" },
    sourcePosition: Position.Right,
    targetPosition: Position.Left,
  },
  {
    id: "risk",
    position: { x: 850, y: 50 },
    data: { label: "Risk Control" },
    style: { borderColor: "var(--color-red)", borderLeftWidth: "4px" },
    sourcePosition: Position.Right,
    targetPosition: Position.Left,
  },
  {
    id: "execution",
    position: { x: 850, y: 250 },
    data: { label: "Execution" },
    style: { borderColor: "var(--color-green)", borderLeftWidth: "4px" },
    sourcePosition: Position.Right,
    targetPosition: Position.Left,
  },
];

const initialEdges: Edge[] = [
  { id: "e1-2", source: "collector", target: "analysts", animated: true },
  { id: "e2-3", source: "analysts", target: "debate", animated: true },
  { id: "e3-4", source: "debate", target: "trader", animated: true },
  { 
    id: "e4-5", 
    source: "trader", 
    target: "risk", 
    markerEnd: { type: MarkerType.ArrowClosed, color: "var(--color-red)" },
    style: { stroke: "var(--color-red)" }
  },
  { 
    id: "e4-6", 
    source: "trader", 
    target: "execution", 
    markerEnd: { type: MarkerType.ArrowClosed, color: "var(--color-green)" },
    style: { stroke: "var(--color-green)" }
  },
];

export function AgentFlowPage() {
  const nodeTypes = useMemo(() => ({}), []);

  return (
    <CyberpunkLayout pageTitle="AGENT_FLOW_MONITOR">
      <div style={{ height: "calc(100vh - 160px)", background: "rgba(10, 10, 15, 0.5)", border: "1px solid var(--color-border)" }}>
        <ReactFlow
          nodes={initialNodes}
          edges={initialEdges}
          nodeTypes={nodeTypes}
          fitView
          onConnect={() => {}}
        >
          <Background color="#333" gap={20} />
          <Controls />
        </ReactFlow>
      </div>

      <div style={{ marginTop: "20px", display: "grid", gridTemplateColumns: "1fr 1fr", gap: "20px" }}>
        <div className="cyber-card" style={{ borderColor: "var(--color-magenta)" }}>
          <h4 style={{ color: "var(--color-magenta)", margin: "0 0 10px 0" }}>NODE_INFO</h4>
          <p style={{ color: "var(--color-text-soft)", fontSize: "12px", fontFamily: "var(--font-mono)" }}>
            SELECTED_ID: <span style={{ color: "#fff" }}>analysts_v1</span><br />
            STATUS: <span style={{ color: "var(--color-green)" }}>RUNNING</span><br />
            INPUT: <span style={{ color: "#fff" }}>{'{ "data": "binance_ohlcv" }'}</span><br />
            OUTPUT: <span style={{ color: "#fff" }}>{'{ "signal": "BUY" }'}</span><br />
            LATENCY: <span style={{ color: "var(--color-yellow)" }}>1.2s</span>
          </p>
        </div>

        <div className="cyber-card" style={{ borderColor: "var(--color-cyan)" }}>
          <h4 style={{ color: "var(--color-cyan)", margin: "0 0 10px 0" }}>GRAPH_STATISTICS</h4>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "10px", textAlign: "center" }}>
            <div>
              <div style={{ color: "var(--color-text-soft)", fontSize: "10px" }}>NODES</div>
              <div style={{ fontSize: "20px", fontWeight: 800 }}>6</div>
            </div>
            <div>
              <div style={{ color: "var(--color-text-soft)", fontSize: "10px" }}>TPS</div>
              <div style={{ fontSize: "20px", fontWeight: 800 }}>12.4</div>
            </div>
            <div>
              <div style={{ color: "var(--color-text-soft)", fontSize: "10px" }}>UPTIME</div>
              <div style={{ fontSize: "20px", fontWeight: 800 }}>142h</div>
            </div>
          </div>
        </div>
      </div>
    </CyberpunkLayout>
  );
}
