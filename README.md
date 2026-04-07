# 来财 (Attract-wealth) — AI 驱动量化交易客户端

<p align="center">
  <h1>🐉 来财 (Attract-wealth)</h1>
  <p><strong>AI 驱动的量化交易研究与分析客户端</strong></p>
  <p>融合 OpsSentry + TradingAgents + OpenHarness + OpenSpace 等 8 大开源项目</p>
</p>

---

## ✨ 核心特性

- 🤖 **多 Agent 协作** — 5 类分析师 + 多空辩论研究员 + 交易员 + 风控团队 (基于 LangGraph)
- 📊 **A 股全覆盖** — Tushare / AkShare / BaoStock 三数据源
- 💰 **实盘交易** — 双通道架构: miniQMT 官方 API + 同花顺 UI 自动化
- 🛡️ **硬编码风控** — 6 条不可绕过的交易安全红线
- 🧬 **策略自进化** — 自动修复/改进/学习交易策略 (OpenSpace 引擎)
- 🧠 **交易记忆** — HOT/WARM/COLD 三层知识沉淀
- 🔌 **LLM 自由切换** — OpenAI 兼容协议, 支持 DeepSeek/Qwen/Kimi/GPT/Ollama
- 🖥️ **Cyberpunk 界面** — React + Vite + TailwindCSS 赛博朋克风格

## 🚀 快速开始

### 环境要求
- Python 3.10+
- Node.js 18+ (前端)

### 安装
```bash
# 克隆项目
git clone https://github.com/btnalit/Attract-wealth.git
cd Attract-wealth

# 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate  # Windows

# 安装依赖
pip install -e ".[all]"

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入 LLM API Key 等配置

# 初始化数据库
python -m src.core.storage

# 启动
python -m src.main
```

访问 http://localhost:8000/docs 查看 API 文档。

## 🏗️ 技术架构

```
核心引擎 (OpsSentry)  →  多 Agent 体系 (TradingAgents)
       ↓                          ↓
数据层 (TradingAgents-CN)  ←→  自进化系统 (OpenSpace)
       ↓                          ↓
交易执行层 (模拟/同花顺/QMT)  →  审计账本 (WAL)
       ↓
前端 (React Cyberpunk HUD)
```

## 📝 License

MIT License

## ⚠️ 风险声明

本项目仅供学习研究使用，不构成任何投资建议。自动化交易存在风险，使用实盘功能前请充分了解风险并在模拟环境中验证策略。
