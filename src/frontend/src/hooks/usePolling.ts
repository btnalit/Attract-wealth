import { useEffect, useRef } from 'react';

/**
 * 定时轮询 hook（F5）。
 *
 * 为需要实时性但无 SSE 推流的页面提供统一的轮询机制。
 * - 组件挂载时立即执行一次，之后按 interval 毫秒周期重复。
 * - 页面隐藏（document.hidden）时暂停轮询，节省资源；可见时立即触发一次并恢复。
 * - 使用 ref 持有最新回调，避免闭包陈旧；依赖变化时自动重置定时器。
 *
 * 使用示例：
 *   usePolling(() => void fetchOverview(), 10000);  // 每 10 秒刷新
 *
 * @param callback 轮询回调（通常是 async fetch 函数）
 * @param interval 轮询间隔（毫秒），<=0 表示禁用
 */
export function usePolling(callback: () => void, interval: number): void {
  const savedCallback = useRef(callback);

  useEffect(() => {
    savedCallback.current = callback;
  }, [callback]);

  useEffect(() => {
    if (interval <= 0) return;

    let timer: number | null = null;

    const tick = () => {
      // 页面不可见时跳过本轮，避免后台无意义的网络请求
      if (document.hidden) return;
      savedCallback.current();
    };

    const start = () => {
      if (timer !== null) return;
      timer = window.setInterval(tick, interval);
    };

    const stop = () => {
      if (timer !== null) {
        window.clearInterval(timer);
        timer = null;
      }
    };

    const onVisibilityChange = () => {
      if (document.hidden) {
        stop();
      } else {
        // 页面重新可见时立即拉一次，再恢复轮询
        tick();
        start();
      }
    };

    start();
    document.addEventListener('visibilitychange', onVisibilityChange);

    return () => {
      stop();
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, [interval]);
}
