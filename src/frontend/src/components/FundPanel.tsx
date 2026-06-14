/**
 * FundPanel —— 个股资金面展示面板（资金 tab 用）。
 *
 * 展示主力资金流、龙虎榜、板块信息、融资融券。
 * 数据来自 analyze 结果的 context。
 */
import { TrendingDown, TrendingUp } from 'lucide-react';
import type { FC } from 'react';
import type { AnalyzeResult } from '../services/api';
import { cn } from '../lib/utils';

interface FundPanelProps {
  analyzeResult: AnalyzeResult | null;
  quote?: {
    price?: number;
    change_pct?: number;
    amount?: number;
    turnover?: number;
    volume?: number;
  } | null;
}

const fmtYi = (value: unknown): string => {
  const n = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(n)) return '--';
  return `${(n / 1e8).toFixed(2)} 亿`;
};

const fmtNum = (value: unknown, digits = 2): string => {
  const n = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(n)) return '--';
  return n.toFixed(digits);
};

export const FundPanel: FC<FundPanelProps> = ({ analyzeResult, quote }) => {
  const ctx = analyzeResult?.state?.context ?? {};
  const moneyFlow = (ctx.money_flow ?? {}) as Record<string, unknown>;
  const dragonTiger = (ctx.dragon_tiger ?? []) as Array<Record<string, unknown>>;
  const sectorInfo = (ctx.sector_info ?? {}) as Record<string, unknown>;
  const margin = (ctx.margin ?? {}) as Record<string, unknown>;

  const hasAny = Object.keys(moneyFlow).length || dragonTiger.length || Object.keys(sectorInfo).length || Object.keys(margin).length;

  if (!analyzeResult) {
    return (
      <div className="flex h-full flex-col items-center justify-center text-info-gray/40 gap-2 py-8">
        <TrendingUp className="h-8 w-8 opacity-30" />
        <span className="text-[10px]">点击"开始分析"后查看资金面数据</span>
      </div>
    );
  }

  if (!hasAny) {
    return (
      <div className="text-[10px] text-info-gray/40 italic py-4 text-center">
        暂无资金面数据（数据源可能被限流，稍后重试）
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* 主力资金流 */}
      {Object.keys(moneyFlow).length > 0 && (
        <div>
          <div className="text-[9px] text-info-gray/50 uppercase font-bold mb-2">主力资金流</div>
          <div className="space-y-1.5">
            <FlowRow label="主力净流入" value={moneyFlow.main_net} pct={moneyFlow.main_net_pct} />
            <FlowRow label="超大单" value={moneyFlow.super_large_net} />
            <FlowRow label="大单" value={moneyFlow.large_net} />
            <FlowRow label="中单" value={moneyFlow.medium_net} />
            <FlowRow label="小单" value={moneyFlow.small_net} />
            {moneyFlow.recent_main_net_sum !== undefined && (
              <FlowRow label="近N日累计" value={moneyFlow.recent_main_net_sum} />
            )}
          </div>
        </div>
      )}

      {/* 龙虎榜 */}
      {dragonTiger.length > 0 && (
        <div>
          <div className="text-[9px] text-info-gray/50 uppercase font-bold mb-2">
            龙虎榜 ({dragonTiger.length} 次)
          </div>
          <div className="space-y-1.5">
            {dragonTiger.slice(0, 5).map((item, i) => (
              <div key={i} className="p-1.5 rounded bg-bg-primary/40 border border-border/40 text-[10px]">
                <div className="flex justify-between">
                  <span className="text-info-gray/60">{String(item.date ?? '')}</span>
                  <span className={cn('font-mono', Number(item.net) >= 0 ? 'text-up-green' : 'text-down-red')}>
                    {Number(item.net) >= 0 ? '+' : ''}{fmtYi(item.net)}
                  </span>
                </div>
                {item.reason && <div className="text-info-gray/50 mt-0.5">{String(item.reason)}</div>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 所属板块 */}
      {Object.keys(sectorInfo).length > 0 && (
        <div>
          <div className="text-[9px] text-info-gray/50 uppercase font-bold mb-2">所属板块</div>
          <div className="space-y-1 text-[10px]">
            {sectorInfo.industry && <InfoRow label="行业" value={sectorInfo.industry} />}
            {sectorInfo.concept && <InfoRow label="概念" value={sectorInfo.concept} />}
            {sectorInfo.total_market_cap && <InfoRow label="总市值" value={fmtYi(sectorInfo.total_market_cap)} />}
            {sectorInfo.circulating_market_cap && <InfoRow label="流通市值" value={fmtYi(sectorInfo.circulating_market_cap)} />}
          </div>
        </div>
      )}

      {/* 融资融券 */}
      {Object.keys(margin).length > 0 && (
        <div>
          <div className="text-[9px] text-info-gray/50 uppercase font-bold mb-2">融资融券</div>
          <div className="space-y-1 text-[10px]">
            {margin.finance_balance && <InfoRow label="融资余额" value={fmtYi(margin.finance_balance)} />}
            {margin.finance_buy && <InfoRow label="融资买入" value={fmtYi(margin.finance_buy)} />}
            {margin.securities_balance && <InfoRow label="融券余额" value={fmtYi(margin.securities_balance)} />}
          </div>
        </div>
      )}
    </div>
  );
};

const FlowRow: FC<{ label: string; value: unknown; pct?: unknown }> = ({ label, value, pct }) => {
  const n = typeof value === 'number' ? value : Number(value);
  const positive = Number.isFinite(n) && n >= 0;
  return (
    <div className="flex justify-between items-center text-[10px]">
      <span className="text-info-gray/60">{label}</span>
      <div className="flex items-center gap-2">
        {pct !== undefined && pct !== null && (
          <span className="text-info-gray/40 text-[9px]">{fmtNum(pct, 1)}%</span>
        )}
        <span className={cn('font-mono font-bold', positive ? 'text-up-green' : 'text-down-red')}>
          {positive ? '+' : ''}{fmtYi(value)}
        </span>
      </div>
    </div>
  );
};

const InfoRow: FC<{ label: string; value: unknown }> = ({ label, value }) => (
  <div className="flex justify-between">
    <span className="text-info-gray/60">{label}</span>
    <span className="text-info-gray/90 font-mono">{String(value ?? '--')}</span>
  </div>
);

export default FundPanel;
