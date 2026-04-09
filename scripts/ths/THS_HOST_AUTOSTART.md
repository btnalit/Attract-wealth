# THS 宿主脚本自动拉起方案

## 目标
- 你登录 `xiadan.exe` 后，`laicai_bridge.py` 由 THS 宿主脚本自动拉起。
- 来财只接受宿主 runtime（`in_ths_api` / `in_xiadan_api` 至少一个为 `true`）。
- 避免“外部 python 启动 bridge 导致 mock 成功”的假连通。

## 一键流程
在项目根目录执行：

```bash
python scripts/ths/run_host_autostart_flow.py --mode paper --start-xiadan-if-missing
```

真实券商模式：

```bash
python scripts/ths/run_host_autostart_flow.py --mode real --start-xiadan-if-missing
```

如果你要把“资金/持仓必须拉通”作为硬门禁：

```bash
python scripts/ths/run_host_autostart_flow.py --mode paper --require-snapshot
```

如果你要单独验证 `easytrader` 回退通道是否可读资金/持仓：

```bash
python scripts/ths/run_easytrader_probe.py --include-orders --include-trades --auto-delegate-32bit
```

如果已安装 32 位 Python，可显式指定：

```bash
python scripts/ths/run_easytrader_probe.py --include-orders --include-trades --auto-delegate-32bit --python32-path C:\Python311-32\python.exe
```

如果你要“一步完成 32 位 Python 检测 + 依赖安装 + 权限检查 + 自动复测”：

```bash
python scripts/ths/run_easytrader_setup_and_probe.py
```

安全说明（避免误关交易客户端）：
- `probe_easytrader_readiness` 默认 `close_client=false`，探针不会调用 `client.exit()`。
- `THSBroker.disconnect()` 默认不会关闭 `xiadan` 进程。
- 只有显式设置 `THS_AUTO_CLOSE_ON_DISCONNECT=true` 才会在断开时调用 `client.exit()`。
- `run_easytrader_probe.py` 会输出运行时守卫信息（位数/权限/进程可访问性），用于快速定位 `WinError 5` 和 32 位不匹配问题。
- `run_easytrader_setup_and_probe.py` 会在复测成功后附带关键交易信息摘要（账户标识/总资产/可用资金/持仓数/当日委托数/当日成交数）。

## 流程做了什么
1. 安装宿主自动拉起文件（幂等）
- 覆盖 `D:\同花顺软件\同花顺\script\laicai_bridge.py`
- 写入 `D:\同花顺软件\同花顺\script\laicai_host_bootstrap.py`
- 向 `D:\同花顺软件\同花顺\script\信号策略\my_signals.py` 注入自动拉起片段

2. 探测宿主 runtime
- 轮询 `127.0.0.1:8089`
- 校验 `ping.runtime`
- 识别当前账号上下文（`users.ini` / `xiadan.ini`）
- 拉取 `get_trade_snapshot` 并输出资金/持仓统计
- 在 runtime 失败或告警时自动追加 easytrader 诊断，区分“桥未加载”与“交易端不可控”

3. 执行 THS 模式 gate（宿主优先）
- 调用 `run_ths_mode_gate.py --host-runtime-only`
- 禁用“外部 bridge 自动拉起”，防止 mock 误通过

## 报告产物
- 安装报告：`data/smoke/reports/ths_host_autostart_install_latest.json`
- 宿主探针报告：`data/smoke/reports/ths_host_runtime_probe_latest.json`
- easytrader 探针报告：`data/smoke/reports/ths_easytrader_probe_latest.json`
- 流程总报告：`data/smoke/reports/ths_host_autostart_flow_*.json`
- 模式 gate 报告：`data/smoke/reports/oneclick_ths_<mode>_host_latest.json`

## 深度扫描结论（除 script 外）
已扫描 `D:\同花顺软件\同花顺` 目录，关键发现：
- `dui_skin/py/*.xml`：可确认存在“策略条件单/Python策略编辑器”UI模块。
- `users.ini` / `xiadan.ini`：可识别登录账号与模拟盘信息（例如 `AI_USER_ACCOUNT`、`TCP/IP_NAME0`）。
- 未发现稳定、公开、可配置的“登录即自动执行任意 Python 文件”的 ini 开关。

结论：
- 当前可控、稳定方案仍是：
  - 注入 `my_signals.py` 自动拉起片段
  - 宿主侧触发策略脚本加载（通常是打开一次“策略条件单/信号策略”）
- 一旦宿主脚本已加载，bridge 会自动启动并可被来财标准门禁验证。

## 常见失败与处理
- `runtime probe failed`
  - 确认 `xiadan.exe` 已登录。
  - 在同花顺里打开一次“策略条件单/信号策略”，再重跑。

- `snapshot failed` 或资金为空
  - runtime 可能已通，但交易域还未初始化。
  - 在交易客户端确认账户页/资金页加载完成后重试。

- `ths_ipc_runtime invalid: mock runtime`
  - 说明仍在走外部 Python bridge（非宿主）。
  - 必须使用本方案的宿主自动拉起链路。
