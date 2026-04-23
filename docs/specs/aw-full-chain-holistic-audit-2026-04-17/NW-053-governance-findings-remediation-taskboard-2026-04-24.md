# NW-053 任务看板（审查问题闭环修复）

> 任务 ID：NW-053  
> 状态：Done  
> 对应规格：`D:\来财\Attract-wealth\docs\specs\aw-full-chain-holistic-audit-2026-04-17\NW-053-governance-findings-remediation-spec-2026-04-24.md`  
> 对应审计：`D:\来财\Attract-wealth\docs\specs\aw-full-chain-holistic-audit-2026-04-17\NW-053-governance-findings-remediation-audit-2026-04-24.md`

## 1. 执行清单

| ID | 优先级 | 任务 | 状态 | 验收标准 |
|---|---|---|---|---|
| NW53-01 | P0 | 补齐 NW-053 spec/audit/taskboard | Done | 三件套齐备 |
| NW53-02 | P0 | TradingVM 去 Router 反向依赖 | Done | 核心层不再 import `src.routers.stream` |
| NW53-03 | P0 | system 路由 Ledger 查询下沉到 Service | Done | 路由不直连 Ledger |
| NW53-04 | P0 | monitor kline interval 全链透传生效 | Done | Router->Service->Dataflow 参数打通 |
| NW53-05 | P0 | strict gate 支持无实体 live 环境降级 | Done | 8089 不可达不再阻断 simulation 基线 |
| NW53-06 | P0 | 补齐/更新测试映射并执行守门 | Done | pytest + lint/build + strict gate 通过 |

## 2. 风险跟踪

| 风险 | 当前状态 | 处置策略 |
|---|---|---|
| 守门降级策略误伤实体联调口径 | Mitigated | 提供 `--require-live-channels` 显式强约束开关 |
| 事件发布器改造影响实时 SSE 展示 | Mitigated | 默认 no-op + `main` 显式注入 stream 发布器 |
| K 线周期映射与历史行为兼容性 | Mitigated | 默认 daily 不变，周期映射仅作用于显式 interval |
