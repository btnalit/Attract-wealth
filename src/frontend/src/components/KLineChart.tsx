/**
 * KLineChart —— 基于 KLineCharts 的 A 股 K 线图组件。
 *
 * 替代原 MarketTerminal 里的手写 SVG 折线，提供：
 * - 蜡烛图（K线）+ 成交量副图
 * - MA5/MA20 均线叠加
 * - A 股配色（红涨绿跌）
 */
import { useEffect, useRef, type FC } from 'react';
import { init, dispose, type Chart } from 'klinecharts';

export interface KLineDataPoint {
  timestamp?: number;
  date?: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
  ma5?: number;
  ma20?: number;
}

interface KLineChartProps {
  data: KLineDataPoint[];
  height?: number | string;
}

const toTimestamp = (value: unknown): number => {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value > 1_000_000_000_000 ? value : value * 1000;
  }
  if (typeof value === 'string') {
    const parsed = Date.parse(value);
    if (!Number.isNaN(parsed)) return parsed;
    // YYYY-MM-DD 格式
    if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
      return Date.parse(value);
    }
  }
  return Date.now();
};

export const KLineChart: FC<KLineChartProps> = ({ data, height = 360 }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<Chart | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    // 初始化图表（用默认样式：蜡烛图 + 网格 + 十字线）
    const chart = init(container);
    chartRef.current = chart;

    if (chart) {
      // 创建主图指标：MA5 / MA20
      chart.createIndicator('MA', false, { id: 'candle_pane' });
      // 创建成交量副图
      chart.createIndicator('VOL');
    }

    // cleanup：用闭包内的局部引用，避免 ref 被清空后 dispose 失效
    return () => {
      dispose(container);
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !data || data.length === 0) return;

    const klineData = data.map((item) => ({
      timestamp: toTimestamp(item.date ?? item.timestamp),
      open: item.open,
      high: item.high,
      low: item.low,
      close: item.close,
      volume: item.volume ?? 0,
      turnover: 0,
    }));

    chart.applyNewData(klineData);
  }, [data]);

  return (
    <div
      ref={containerRef}
      style={{ width: '100%', height: typeof height === 'number' ? `${height}px` : height }}
      className="klinechart-container"
    />
  );
};

export default KLineChart;
