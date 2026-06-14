import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';


export const useHotkeys = (onOpenCommandPalette: () => void) => {
  const navigate = useNavigate();

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

      // Quick Navigation: Alt+1 ~ Alt+9（F9：原为裸数字键，会干扰页面其他交互）
      if (e.altKey && !e.metaKey && !e.ctrlKey && !e.shiftKey && e.key >= '1' && e.key <= '9') {
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
          e.preventDefault();
          navigate(routes[index]);
        }
      }

      // Refresh: Ctrl+R / Cmd+R（F3：原为裸 R 键，会丢失未保存数据）
      // 现在遵循浏览器原生快捷键约定，不再拦截裸 R。
      // 注意：浏览器原生 Ctrl+R 已能刷新，这里不重复处理。
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [navigate, onOpenCommandPalette]);
};
