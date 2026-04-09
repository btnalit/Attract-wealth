import React from 'react';
import { Route, Routes } from 'react-router-dom';
import CyberpunkLayout from './components/CyberpunkLayout';

// Pages
import Dashboard from './pages/Dashboard';
import MarketTerminal from './pages/MarketTerminal';
import AgentWorkshop from './pages/AgentWorkshop';
import EvolutionCenter from './pages/EvolutionCenter';
import MemoryVault from './pages/MemoryVault';
import KnowledgeHub from './pages/KnowledgeHub';
import ExecutionMonitor from './pages/ExecutionMonitor';
import StrategyMatrix from './pages/StrategyMatrix';
import BacktestLab from './pages/BacktestLab';
import AuditRisk from './pages/AuditRisk';
import LogTerminal from './pages/LogTerminal';
import SystemConfig from './pages/SystemConfig';

export default function App() {
  return (
    <Routes>
      <Route element={<CyberpunkLayout />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/market" element={<MarketTerminal />} />
        <Route path="/agents" element={<AgentWorkshop />} />
        <Route path="/evolution" element={<EvolutionCenter />} />
        <Route path="/memory" element={<MemoryVault />} />
        <Route path="/knowledge" element={<KnowledgeHub />} />
        <Route path="/execution" element={<ExecutionMonitor />} />
        <Route path="/strategies" element={<StrategyMatrix />} />
        <Route path="/backtest" element={<BacktestLab />} />
        <Route path="/audit" element={<AuditRisk />} />
        <Route path="/logs" element={<LogTerminal />} />
        <Route path="/settings" element={<SystemConfig />} />
      </Route>
    </Routes>
  );
}
