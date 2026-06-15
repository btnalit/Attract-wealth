# 🐉 来财 (LaiCai) — AI 驱动的量化交易终端

> **Attract-wealth (来财)** 是一个基于 Python + FastAPI + React 的开源 AI 量化交易研究与分析平台。
> 它融合了 8 大开源项目的精华，打造了一个具备**多 Agent 协作、策略自进化、三层记忆系统**的赛博朋克风格交易大脑。

---

## ✨ 核心特性

- 🤖 **多 Agent 协作网络** — 基于 LangGraph 编排：基本面/技术/新闻/情绪分析师 → 多空辩论 → 交易决策 → 风控拦截。
- 🧬 **策略自进化 (Evolution)** — 具备 FIX/DERIVED/CAPTURED 三大进化模式，能从交易得失中自动迭代策略。
- 🧠 **三层记忆系统 (Memory)** — HOT (热) / WARM (温) / COLD (冷) 分层存储交易经验，支持自动晋升与遗忘。
- 📊 **A 股多数据源** — 同时支持 AkShare, Tushare, BaoStock 数据接入与无缝切换。
- 🛡️ **硬核风控 (RiskGate)** — 内置 6 条不可绕过的交易红线（回撤/持仓/频次/白名单），保障资金安全。
- 🖥️ **赛博朋克控制台** — React + Vite + Tailwind 构建的 11 页专业 HUD，支持 AgentFlow 实时可视化。
- 🔌 **LLM 自由切换** — OpenAI 兼容协议，支持 DeepSeek, Qwen, Kimi, GPT-4o, Claude 等任意模型。
- 🪟 **Windows 原生部署** — 内置同花顺路径自适应探测器 (ThsPathResolver)，双击「一键启动.bat」自动检测环境并启动。

---

## 📥 下载与启动

### 方式一：一键启动（推荐，Windows 用户）

1. **克隆/下载源码**
   ```bash
   git clone https://github.com/btnalit/Attract-wealth.git
   ```
   或到 [Releases](https://github.com/btnalit/Attract-wealth/releases) 下载源码包解压。

2. **双击 `一键启动.bat`**

   脚本会自动完成全部初始化：
   - 检测/安装 Python 3.10+（可选 winget 自动安装）
   - 创建 `.venv` 虚拟环境
   - 安装 Python 依赖（`requirements.txt`）
   - 检测/安装 Node.js 并构建前端（可选 winget 自动安装）
   - 从 `.env.example` 生成 `.env` 配置（首次会提示编辑）
   - 检测同花顺路径（可选）
   - 启动后端服务

3. **配置 LLM（必需）**

   首次启动前，编辑项目根目录 `.env` 文件，至少填写：
   ```env
   LLM_API_KEY=sk-your-key        # AI 分析必需（默认 deepseek）
   LLM_BASE_URL=https://api.deepseek.com
   TRADING_CHANNEL=simulation     # 模拟盘（无需券商）
   ```

4. **访问系统**
   - 🌐 控制台: http://127.0.0.1:8000
   - 📖 API 文档: http://127.0.0.1:8000/docs

> 💡 首次初始化完成后，日常启动只需双击 `启动.bat`（跳过环境检测，秒启）。

### 方式二：手动安装（开发/非 Windows）

```bash
git clone https://github.com/btnalit/Attract-wealth.git
cd Attract-wealth

# Python 环境
python -m venv .venv
.venv\Scripts\activate          # Windows | source .venv/bin/activate (Linux/Mac)
pip install -r requirements.txt

# 前端构建（可选，不构建则用 npm run dev 开发模式）
cd src/frontend && npm install && npm run build && cd ../..

# 配置
cp .env.example .env            # 编辑 .env 填写 LLM_API_KEY 等

# 启动
python -m uvicorn src.main:app --host 127.0.0.1 --port 8000
```

### 启动脚本说明

| 脚本 | 用途 |
|------|------|
| `一键启动.bat` | 完整环境检测 + 依赖安装 + 前端构建 + 启动。**首次运行用这个。** |
| `启动.bat` | 快速启动（假设 `.venv` 已就绪）。**日常运行用这个。** |

---

## 🚀 实盘交易通道

来财默认使用 `simulation`（模拟盘），无需任何券商配置。切换实盘通道需在 `.env` 设置 `TRADING_CHANNEL`：

| 通道 | 说明 | 需要的配置 |
|------|------|-----------|
| `simulation` | 本地模拟撮合（默认，零风险） | 无 |
| `ths_ipc` | 同花顺 IPC 桥（需运行 bridge 脚本） | `THS_IPC_*` |
| `ths_auto` | 同花顺 UI 自动化（pywinauto） | `THS_EXE_PATH` 等 |
| `qmt` | miniQMT（需 xtquant） | `QMT_PATH` 等 |

> ⚠️ 实盘前务必在模拟盘充分验证策略。`RiskGate` 的 6 条红线（回撤/持仓/频次/白名单等）在所有通道下强制生效。

---

## 🏗️ 技术架构

```
┌────────────────────────────────────────────────────────┐
│               Frontend (React + Vite)                  │
│  Dashboard | AgentFlow | Evolution | Strategy Matrix   │
└──────────────────────────┬─────────────────────────────┘
                           │ REST / SSE
┌──────────────────────────┴─────────────────────────────┐
│                 FastAPI Backend                          │
│                                                        │
│  TradingVM (LangGraph) ←→ 多 Agent 协同                 │
│       ↕                      ↕                         │
│  Execution Layer (Sim/THS/QMT) ←→ RiskGate (风控)      │
│       ↕                                                 │
│  Evolution Layer (策略进化器 + 记忆系统 + 知识库)        │
└────────────────────────────────────────────────────────┘
```

---

## 📦 持续集成 (CI)

本项目配置了 GitHub Actions，包含两个 CI 门禁 job：

- **Lint & Test**：ruff 检查 + pytest 单元测试（Windows runner）
- **Build Frontend**：npm install + vite build，验证前端可正常构建

推送 `v*` 版本标签时，额外触发**源码 Release**（打包源码 zip 上传到 Releases 页面）：

```bash
git tag v0.1.0
git push origin v0.1.0
```

> 本项目已从 PyInstaller exe 打包方案切换为**源码 + 一键启动脚本**方案。
> 量化交易系统含 GUI 自动化（pywinauto/pyautogui）和重型数据依赖（baostock/lancedb），
> 打包成单 exe 体积大、启动慢、平台相关库易崩溃；源码方案更透明、可调试、易更新。

---

## 📝 License

MIT License

## ⚠️ 风险声明

本项目仅供学习研究使用，不构成任何投资建议。自动化交易存在风险，使用实盘功能前请充分了解风险并在模拟环境中验证策略。
