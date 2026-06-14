
import { Link, Route, Routes } from 'react-router-dom';
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

/** 404 兜底页（F7：原无此路由，访问未知路径白屏） */
const NotFound = () => (
  <div className="flex h-full flex-col items-center justify-center gap-4 p-8 text-center font-mono">
    <h1 className="text-6xl font-bold text-neon-cyan">404</h1>
    <p className="text-sm text-info-gray">请求的页面不存在。</p>
    <Link
      to="/"
      className="px-4 py-2 text-xs border border-neon-cyan/50 text-neon-cyan hover:bg-neon-cyan/10 transition-colors rounded-sm"
    >
      返回控制面板
    </Link>
  </div>
);

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
        {/* F7：未知路径兜底，不再白屏 */}
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
