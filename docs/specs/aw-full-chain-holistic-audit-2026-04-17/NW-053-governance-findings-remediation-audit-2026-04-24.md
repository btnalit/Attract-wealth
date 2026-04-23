# NW-053 审查问题闭环修复审计报告

## 1. 基本信息
- 任务 ID：`NW-053`
- 报告日期：2026-04-24
- 当前状态：`Done`
- 对应规格：`D:\来财\Attract-wealth\docs\specs\aw-full-chain-holistic-audit-2026-04-17\NW-053-governance-findings-remediation-spec-2026-04-24.md`
- 对应看板：`D:\来财\Attract-wealth\docs\specs\aw-full-chain-holistic-audit-2026-04-17\NW-053-governance-findings-remediation-taskboard-2026-04-24.md`

## 2. 审计范围
- `src/core/trading_vm.py`
- `src/core/trading_service.py`
- `src/main.py`
- `src/routers/system.py`
- `src/services/system_query_service.py`（新增）
- `src/routers/monitor.py`
- `src/services/monitor_service.py`
- `src/services/dataflow_service.py`
- `scripts/smoke/run_strict_gate.py`
- `tests/unit/test_system_router_baseline.py`
- `tests/unit/test_monitor_router.py`
- `tests/unit/test_backend_layering_convergence.py`
- `tests/unit/test_run_strict_gate.py`

## 3. 基线差距（实施前）
- [x] `TradingVM` 直接依赖 Router 推流函数。
- [x] `system` 路由直接访问 `TradingLedger`。
- [x] `monitor kline` 的 `interval` 参数未生效。
- [x] `strict gate` 在无实体 THS IPC 环境下被硬阻断。

## 4. 目标审计项（实施后）
- [x] 核心层与 Router 解耦（依赖注入事件发布）。
- [x] `system` 路由完成 Service 下沉。
- [x] `interval` 参数 Router -> Service -> Dataflow 全链生效。
- [x] 守门支持“离线 live 通道降级 + 可选强约束”。
- [x] 受影响自动化测试与守门通过。

## 5. 当前结论
- 当前结论：`Pass`
- 关键结果：
  - `TradingVM` 已通过事件发布器注入实现与 Router 解耦，核心层不再直接 import `src.routers.stream`；
  - `system` 路由已通过 `SystemQueryService` 查询 `llm_usage_summary` 与 `decision_evidence`；
  - `monitor kline` 已透传 `interval` 并在 Dataflow 层做 D/W/M 周期映射；
  - `strict gate` 在 THS IPC 离线场景可降级运行，`--check-only` 与离线 matrix 均通过。

## 6. 证据索引（预留）
- `D:\来财\Attract-wealth\docs\specs\aw-full-chain-holistic-audit-2026-04-17\evidence\NW-053\pytest_nw053.log`
- `D:\来财\Attract-wealth\docs\specs\aw-full-chain-holistic-audit-2026-04-17\evidence\NW-053\frontend_lint_nw053.log`
- `D:\来财\Attract-wealth\docs\specs\aw-full-chain-holistic-audit-2026-04-17\evidence\NW-053\frontend_build_nw053.log`
- `D:\来财\Attract-wealth\docs\specs\aw-full-chain-holistic-audit-2026-04-17\evidence\NW-053\strict_gate_nw053.log`
- `D:\来财\Attract-wealth\docs\specs\aw-full-chain-holistic-audit-2026-04-17\evidence\NW-053\matrix_strict_nw053.json`
- `D:\来财\Attract-wealth\docs\specs\aw-full-chain-holistic-audit-2026-04-17\evidence\NW-053\nw053_execution_summary.json`
