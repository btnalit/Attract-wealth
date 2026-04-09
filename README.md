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
- 🪟 **Windows 原生部署** — 内置同花顺路径自适应探测器 (ThsPathResolver) 及一键安装方案 (Inno Setup)。

---

## 📥 下载与使用指南 (Download & Usage)

> **当前版本说明**: 这是一个 **绿色便携版 (Portable Build)**，**无需安装**，解压后双击即可运行。

### 📌 快速启动步骤
1. **打开文件夹**: 解压下载的文件，找到名为 **`laiCai`** 的文件夹（带有齿轮图标）。
2. **运行主程序**: 进入该文件夹，双击运行 **`laiCai.exe`**。
   - *Windows 提示*: 如果是第一次运行，系统可能提示“未知发布者”，请点击 **“更多信息” -> “仍要运行”**。
3. **访问系统**: 
   - 启动后，请保持弹出的黑色控制台窗口运行。
   - 打开浏览器访问：
     - 🌐 **系统控制台 / API**: http://localhost:8000

> *(注：文件夹中出现的 `.spec`、`build` 等文件为构建残留，后续 CI 版本将自动清理，目前请忽略。)*

---

## 🚀 快速开始 (开发环境)

### 环境要求
- Python 3.10+
- Node.js 18+ (前端)
- Git

### 安装与运行

```bash
# 1. 克隆项目
git clone https://github.com/btnalit/Attract-wealth.git
cd Attract-wealth

# 2. 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate  # Windows

# 3. 安装依赖
pip install -e ".[dev]"

# 4. 启动后端 (API + TradingVM)
python -m src.main

# 5. (可选) 启动前端
cd src/frontend
npm install
npm run dev
```

- 后端 API 文档: http://localhost:8000/docs
- 前端控制台: http://localhost:5173

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

## 📦 自动化构建 (CI/CD)

本项目配置了 GitHub Actions 自动化流水线。当您推送 `v*` 版本标签时，GitHub 将自动在 Windows 环境中完成打包：

```bash
# 推送版本标签触发自动构建
git tag v0.1.0
git push origin v0.1.0
```

构建产物将自动上传至项目的 **Releases** 页面。

---

## 📝 License

MIT License

## ⚠️ 风险声明

本项目仅供学习研究使用，不构成任何投资建议。自动化交易存在风险，使用实盘功能前请充分了解风险并在模拟环境中验证策略。
