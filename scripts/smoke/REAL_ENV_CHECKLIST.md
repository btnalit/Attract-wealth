# 真实环境联调 Checklist（THS / QMT）

## 1. 运行前必备
- 项目目录：`D:\来财\Attract-wealth`
- Python 解释器：优先 `.venv\Scripts\python.exe`
- `.env` 至少包含：
  - `TRADING_CHANNEL=ths_ipc`（仅测 THS 时）
  - `THS_IPC_HOST` / `THS_IPC_PORT`
  - `STARTUP_AUTO_START_THS_BRIDGE=true`
  - `THS_BRIDGE_SCRIPT=D:\同花顺软件\同花顺\script\laicai_bridge.py`
  - 可选：`THS_BRIDGE_START_COMMAND=...`（如需走同花顺宿主启动命令）
  - `SMOKE_ALLOW_LIVE_ORDER=true`（要做真实下单探针时必须）
  - `SMOKE_DEFAULT_CHANNELS=ths_ipc,simulation`（无 QMT 实机时建议）
  - `SEALOFF_DEFAULT_PROFILE=ths_sim_strict`

## 2. 服务启动行为（已接入）
- 来财服务启动时，若 `TRADING_CHANNEL=ths_ipc` 且 `STARTUP_AUTO_START_THS_BRIDGE=true`：
  - 自动尝试拉起 THS IPC bridge。
  - 如果配置了 `THS_BRIDGE_START_COMMAND`，优先执行该命令。
  - 否则使用 `THS_BRIDGE_PYTHON + THS_BRIDGE_SCRIPT` 启动。
  - 若端口已就绪则复用，不重复拉起。

- bridge 状态可在以下接口查看：
  - `/api/system/info` 的 `ths_bridge`
  - `/api/system/runtime` 的 `ths_bridge`
  - `/api/system/ths-bridge`
- bridge 手动控制接口：
  - `POST /api/system/ths-bridge/start`
  - `POST /api/system/ths-bridge/stop`

## 3. 通道就绪要求
- `ths_ipc`：同花顺已登录目标账户，bridge 脚本可运行，端口可连通。
- `qmt`：miniQMT 可用，`xtquant` 可导入。
- `stability_probe`：若启用，`pandas` 需可导入。

## 4. 一步执行（THS only）
### 真实券商模式（连通 + 下单探针）
```bash
python scripts/smoke/run_ths_mode_gate.py --mode real
```

### 模拟炒股模式（连通 + 下单探针）
```bash
python scripts/smoke/run_ths_mode_gate.py --mode paper
```

说明：
- 两次执行之间，请先在同花顺内切换账户模式（真实 / 模拟）。
- 默认参数是：
  - `--channels ths_ipc`
  - `--include-order-probe`
  - `--force-live-order`
  - `--no-reconcile`
  - `--no-stability-probe`

## 5. 通用 one-click 入口（跨通道）
```bash
python scripts/smoke/run_oneclick_gate.py
```

默认行为：
- 自动尝试启动 THS bridge。
- 先跑 precheck（check-only），默认 precheck 失败即 fail-fast。
- 再跑 strict gate（默认 `ths_ipc,simulation` + 对账 + 稳定性探针）。

若要补跑 QMT：
```bash
python scripts/smoke/run_oneclick_gate.py --channels ths_ipc,qmt
```

## 6. 常用变体
### 仅 THS 连通（不下单）
```bash
python scripts/smoke/run_oneclick_gate.py --channels ths_ipc --no-reconcile --no-stability-probe
```

### 不自动启动 bridge（手工启动时）
```bash
python scripts/smoke/run_oneclick_gate.py --no-auto-start-ths-bridge
```

### precheck 失败后继续执行（默认 fail-fast）
```bash
python scripts/smoke/run_oneclick_gate.py --no-fail-fast-precheck
```

## 7. 输出与判定
- THS mode 输出：
  - `data/smoke/reports/matrix_ths_real_latest.json`
  - `data/smoke/reports/matrix_ths_paper_latest.json`
  - `data/smoke/reports/oneclick_ths_real_*.json`
  - `data/smoke/reports/oneclick_ths_paper_*.json`

- 通用 one-click 输出：
  - `data/smoke/reports/matrix_strict_latest.json`
  - `data/smoke/reports/oneclick_gate_*.json`

- bridge 日志：
  - `data/smoke/reports/ths_bridge_stdout.log`
  - `data/smoke/reports/ths_bridge_stderr.log`

判定口径：
- 严格门禁通过条件：`all_passed=true`
- 失败时重点看：
  - `hints`
  - `preflight.reason`
  - 单通道 `checks`
  - `stderr`

## 8. THS 宿主自动拉起（推荐）
为避免“外部 python 启动 bridge 导致 mock 误通过”，建议改为宿主脚本自动拉起：

```bash
python scripts/ths/run_host_autostart_flow.py --mode paper
```

真实券商联调：

```bash
python scripts/ths/run_host_autostart_flow.py --mode real
```

详细说明见：`scripts/ths/THS_HOST_AUTOSTART.md`
