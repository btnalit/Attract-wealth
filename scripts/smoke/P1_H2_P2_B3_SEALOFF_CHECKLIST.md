# P1-H2 + P2-B3 实机参数定版与封板执行清单

更新时间：2026-04-08

## 1. 目标

- `P1-H2`：完成 THS/QMT 实机 smoke 联调封板（连通、下单探针、对账链路）。
- `P2-B3`：固定回源限流、退避重试、数据质量阈值参数，并在 smoke 中验证。

## 2. 实机参数定版

### 2.1 交易通道基础参数（.env）

```env
TRADING_CHANNEL=ths_ipc
THS_IPC_HOST=127.0.0.1
THS_IPC_PORT=8089
STARTUP_AUTO_START_THS_BRIDGE=true
THS_BRIDGE_SCRIPT=D:\同花顺软件\同花顺\script\laicai_bridge.py
THS_BRIDGE_START_COMMAND=
SMOKE_ALLOW_LIVE_ORDER=false
```

说明：

- 使用 `run_sealoff_gate.py` 执行时，真实/模拟下单探针 profile 会自动临时设置 `SMOKE_ALLOW_LIVE_ORDER=true`。
- 若使用双通道封板，需额外配置 `QMT_ACCOUNT_ID`（或 `QMT_ACCOUNT`）和 `QMT_PATH`。

### 2.2 P2-B3 基线参数（脚本自动注入）

`scripts/smoke/run_sealoff_gate.py` 默认会注入以下基线：

```env
DATA_PROVIDER_RATE_LIMIT_PER_MINUTE=120
DATA_PROVIDER_MIN_INTERVAL_MS=120
DATA_PROVIDER_MAX_WAIT_MS=400
DATA_PROVIDER_BACKOFF_RETRIES=2
DATA_PROVIDER_BACKOFF_BASE_MS=80
DATA_PROVIDER_BACKOFF_FACTOR=2.0
DATA_PROVIDER_BACKOFF_MAX_MS=1000
DATA_QUALITY_ERROR_WARN=0.15
DATA_QUALITY_ERROR_BLOCK=0.40
DATA_QUALITY_EMPTY_WARN=0.30
DATA_QUALITY_EMPTY_BLOCK=0.70
DATA_QUALITY_RETRY_WARN=0.20
DATA_QUALITY_RETRY_BLOCK=0.60
DATA_QUALITY_RATE_LIMIT_WARN=0.20
DATA_QUALITY_RATE_LIMIT_BLOCK=0.50
DATA_QUALITY_STALE_WARN_DAYS=3
DATA_QUALITY_STALE_BLOCK_DAYS=7
DATA_QUALITY_PROVIDER_ERROR_WARN=0.50
DATA_QUALITY_PROVIDER_ERROR_BLOCK=0.90
DATA_QUALITY_PROVIDER_MIN_REQUESTS=3
```

## 3. 封板 profile 与命令

### 3.1 同花顺真实账户连通 + 下单探针

```bash
python scripts/smoke/run_sealoff_gate.py --profile ths_real_probe --allow-live-order
```

### 3.2 同花顺模拟盘完整链路（含对账 + 稳定性探针）

```bash
python scripts/smoke/run_sealoff_gate.py --profile ths_paper_full --allow-live-order
```

### 3.3 本机主线封板（THS + simulation）

```bash
python scripts/smoke/run_sealoff_gate.py --profile ths_sim_strict
```

### 3.4 本机全探针封板（THS + simulation + 下单探针）

```bash
python scripts/smoke/run_sealoff_gate.py --profile ths_sim_probe --allow-live-order
```

### 3.5 双通道严格封板（THS + QMT，待有 QMT 实机时补跑）

```bash
python scripts/smoke/run_sealoff_gate.py --profile dual_channel_strict
```

### 3.6 应用数据稳定参数 profile（P2-B3）

```bash
python scripts/dataflow/apply_runtime_profile.py --profile ths_paper_default
```

可选压测联动：

```bash
python scripts/dataflow/apply_runtime_profile.py --profile ths_live_safe --run-stability-probe --strict-probe
```

## 4. 标准执行顺序

1. 启动并登录同花顺交易端（真实或模拟，按本轮目标手动切换）。
2. 执行 `ths_real_probe`（验证真实券商链路和下单探针）。
3. 切换到模拟炒股，再执行 `ths_paper_full`（验证完整链路）。
4. 执行 `ths_sim_strict`（验证 THS + simulation 双链路封板）。
5. 若本机具备 QMT，再执行 `dual_channel_strict` 完成双通道封板。

## 5. 验收口径

- `sealoff_report` 中 `gate_summary.all_passed=true`。
- `matrix_report` 中 `all_passed=true` 且 `counts.fail=0`。
- `oneclick_report` 中 `bridge.ready=true`（THS IPC 场景）。
- 若执行了稳定性探针，`stability_probe.status != BLOCK`。

## 6. 失败处理与恢复

- 若出现对账阻断，先查看：
  - `GET /api/system/reconciliation/guard`
- 手动解锁接口：
  - `POST /api/trading/reconcile/unlock`
  - 头部（如配置）：`X-Recon-Unlock-Token: <RECON_UNLOCK_TOKEN>`
- 解锁后建议再次执行对应 profile 做回归复验。

## 7. 产物路径

- 矩阵报告：`data/smoke/reports/matrix_sealoff_<profile>_latest.json`
- one-click 报告：`data/smoke/reports/oneclick_sealoff_<profile>_<timestamp>.json`
- 封板汇总：`data/smoke/reports/sealoff_<profile>_<timestamp>.json`
- THS bridge 日志：
  - `data/smoke/reports/ths_bridge_stdout.log`
  - `data/smoke/reports/ths_bridge_stderr.log`
