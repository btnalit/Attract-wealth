# NW-053 审查问题闭环修复规格（SDD）

> 任务 ID：NW-053  
> 日期：2026-04-24  
> 状态：Done  
> 对应审计：`D:\来财\Attract-wealth\docs\specs\aw-full-chain-holistic-audit-2026-04-17\NW-053-governance-findings-remediation-audit-2026-04-24.md`  
> 对应看板：`D:\来财\Attract-wealth\docs\specs\aw-full-chain-holistic-audit-2026-04-17\NW-053-governance-findings-remediation-taskboard-2026-04-24.md`

## 1. 背景与目标

- 背景：代码级审查新增 3 个问题：
  - 核心层 `TradingVM` 反向依赖 Router 推流。
  - `system` 路由绕过 Service 直连 `TradingLedger`。
  - `monitor kline` 的 `interval` 参数声明后被忽略。
- 背景：严格守门在无实体 THS IPC 环境（`127.0.0.1:8089` 不可达）下被硬阻断，导致 simulation 侧发布验证被误拦。
- 目标：在保持分层治理口径的前提下，完成 3 个代码问题修复，并将守门改造为“无实体 live 环境可降级、实体环境可强约束”。

## 2. 全链路范围（前端 -> API 层 -> 后端 -> Service -> DAO/DB -> 守门）

- 核心执行链：
  - `src/core/trading_vm.py`
  - `src/core/trading_service.py`
  - `src/main.py`
- system 查询链：
  - `src/routers/system.py`
  - `src/services/system_query_service.py`（新增）
  - `src/core/trading_ledger.py`
- monitor K 线链：
  - `src/routers/monitor.py`
  - `src/services/monitor_service.py`
  - `src/services/dataflow_service.py`
  - `src/dataflows/source_manager.py`
- 守门链：
  - `scripts/smoke/run_strict_gate.py`
  - `scripts/smoke/run_channel_matrix.py`
  - `scripts/smoke/live_channel_smoke.py`
- 测试映射：
  - `tests/unit/test_system_router_baseline.py`
  - `tests/unit/test_monitor_router.py`
  - `tests/unit/test_backend_layering_convergence.py`
  - `tests/unit/test_run_strict_gate.py`
  - `tests/unit/test_run_channel_matrix.py`（按需）

## 3. 差距 -> 任务包

- P0-53A：核心层去 Router 反向依赖
  - 差距：`TradingVM` 直接 `from src.routers.stream import ...`。
  - 改造：引入事件发布器依赖注入；核心层仅面向抽象能力，不依赖 Router 模块。

- P0-53B：system 路由补齐 Service 层封装
  - 差距：`/llm/metrics`、`/audit/evidence` 直接访问 `TradingLedger`。
  - 改造：新增 `SystemQueryService`，路由统一经 Service 获取数据。

- P0-53C：monitor kline interval 实参生效
  - 差距：路由层声明 `interval` 但未透传。
  - 改造：参数贯通 Router -> Service -> Dataflow；支持标准周期映射（至少 D/W/M）。

- P0-53D：无实体 THS 环境守门降级策略
  - 差距：`strict gate` 默认把 THS IPC 不可达视为硬失败。
  - 改造：新增可配置策略：无实体 live 环境时允许 live 通道降级（warning/SKIP），实体联调时可启用强约束模式。

## 4. 验收标准

1. `TradingVM` 不再直接 import `src.routers.stream`；
2. `system` 路由不再直接使用 `TradingLedger`，统一经 Service；
3. `monitor kline` 的 `interval` 参数全链透传并有自动化测试覆盖；
4. 严格守门在无实体 THS IPC 环境下不再阻断 simulation 基线；
5. 受影响测试、前端 `lint+build`、严格守门链通过。

## 5. 证据计划

- 目录：`D:\来财\Attract-wealth\docs\specs\aw-full-chain-holistic-audit-2026-04-17\evidence\NW-053\`
- 产物：
  - `pytest_nw053.log`
  - `frontend_lint_nw053.log`
  - `frontend_build_nw053.log`
  - `strict_gate_nw053.log`
  - `matrix_strict_nw053.json`
  - `nw053_execution_summary.json`

## 6. 完成说明（实施后回填）

- 已完成 `TradingVM` 事件发布器注入改造，核心层移除对 `src.routers.stream` 的直接依赖；
- 已新增 `SystemQueryService`，`system` 路由 `/llm/metrics` 与 `/audit/evidence` 统一经 Service 查询；
- 已完成 `interval` 参数 Router -> Service -> Dataflow 贯通，K 线周期支持 D/W/M 映射；
- 已完成 strict gate 离线 live 通道降级策略：无实体 THS 环境下预检降级为 warning，matrix 允许 SKIP；
- 已通过受影响单测、前端 `lint/build`、strict gate（check-only + matrix）。
