---
name: momentum-breakout
description: 动量突破策略 — 当股价突破 N 日新高时买入
version: 1
origin: built-in
---

# 动量突破策略

## 策略逻辑

1. **入场条件**: 股价突破过去 20 日最高价
2. **确认信号**: 成交量放大至 20 日均量的 1.5 倍以上
3. **仓位管理**: 单笔不超过总资产 10%
4. **止损**: 跌破入场价 5%
5. **止盈**: 盈利达 15% 或跌破 5 日均线

## 适用场景
- 趋势行情
- 板块轮动初期

## 参数
```yaml
lookback_days: 20
volume_multiplier: 1.5
position_size: 0.10
stop_loss: -0.05
take_profit: 0.15
trailing_stop_ma: 5
```

## 风险提示
- 震荡市中容易频繁止损
- 需配合大盘趋势判断
