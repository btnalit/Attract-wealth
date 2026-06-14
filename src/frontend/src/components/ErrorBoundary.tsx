import React from 'react';

interface ErrorBoundaryProps {
  children: React.ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

/**
 * 全局错误边界（F4）。
 *
 * 任何子组件抛出未捕获异常时，展示降级 UI 而非白屏。
 * 对交易终端至关重要——白屏期间用户无法撤单、看持仓、停止交易。
 *
 * 提供"返回首页"和"重置"两个动作：
 * - 返回首页：导航到 / 并重置错误状态
 * - 重置：仅清除错误状态，尝试重新渲染当前页面
 */
export class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo): void {
    // 记录到控制台便于排查；生产环境可接入监控上报
    console.error('[ErrorBoundary] 未捕获异常:', error, info.componentStack);
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
  };

  handleGoHome = () => {
    this.setState({ hasError: false, error: null });
    window.location.href = '/';
  };

  render(): React.ReactNode {
    if (this.state.hasError) {
      const errMsg = this.state.error?.message ?? '未知错误';
      const errStack = this.state.error?.stack ?? '';
      return (
        <div className="flex h-screen w-screen flex-col items-center justify-center gap-4 bg-bg-primary p-8 text-center font-mono">
          <div className="border border-down-red/50 bg-bg-card/80 p-8 rounded-sm max-w-2xl">
            <h1 className="text-2xl font-bold text-down-red mb-2">⚠ 页面渲染异常</h1>
            <p className="text-sm text-info-gray mb-4">
              组件抛出了未捕获的异常。交易终端已降级显示，避免完全白屏。
            </p>
            <div className="text-left text-xs text-info-gray/70 bg-bg-primary/50 p-3 rounded-sm border border-border overflow-auto max-h-48 mb-4">
              <div className="text-down-red font-bold mb-1">{errMsg}</div>
              {errStack && <pre className="whitespace-pre-wrap break-all">{errStack}</pre>}
            </div>
            <div className="flex gap-3 justify-center">
              <button
                onClick={this.handleReset}
                className="px-4 py-2 text-xs border border-border hover:border-neon-cyan/50 hover:text-neon-cyan transition-colors rounded-sm"
              >
                重试当前页
              </button>
              <button
                onClick={this.handleGoHome}
                className="px-4 py-2 text-xs border border-neon-cyan/50 text-neon-cyan hover:bg-neon-cyan/10 transition-colors rounded-sm"
              >
                返回首页
              </button>
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

export default ErrorBoundary;
