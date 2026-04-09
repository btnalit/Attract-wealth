import { useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';


export const useHotkeys = (onOpenCommandPalette: () => void) => {
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Check if user is typing in an input/textarea
      if (
        document.activeElement?.tagName === 'INPUT' ||
        document.activeElement?.tagName === 'TEXTAREA' ||
        (document.activeElement as HTMLElement)?.isContentEditable
      ) {
        if (e.key === 'Escape') {
          (document.activeElement as HTMLElement).blur();
        }
        return;
      }

      // Command Palette: Cmd+K or Ctrl+K
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        onOpenCommandPalette();
      }

      // Quick Navigation: 1-9
      if (!e.metaKey && !e.ctrlKey && !e.altKey && e.key >= '1' && e.key <= '9') {
        const routes = [
          '/',          // 1: Dashboard
          '/market',    // 2: Market
          '/agents',    // 3: Agents
          '/evolution', // 4: Evolution
          '/memory',    // 5: Memory
          '/knowledge', // 6: Knowledge
          '/execution', // 7: Execution
          '/strategies',// 8: Strategies
          '/backtest',  // 9: Backtest
        ];
        const index = parseInt(e.key) - 1;
        if (routes[index]) {
          navigate(routes[index]);
        }
      }

      // Refresh: R
      if (e.key.toLowerCase() === 'r' && !e.metaKey && !e.ctrlKey) {
        window.location.reload();
      }

      // Quick Start/Stop Trading: Space (Only on Agents page)
      if (e.key === ' ' && location.pathname === '/agents') {
        e.preventDefault();
        console.log('Toggle Trading Status');
        // This would typically interact with a global state or service
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [navigate, location, onOpenCommandPalette]);
};
