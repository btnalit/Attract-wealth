"""
来财 (Attract-wealth) — FastAPI 应用入口
AI 驱动量化交易客户端
"""
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # ---- 启动 ----
    print("🐉 来财 (Attract-wealth) 正在启动...")
    # TODO: 初始化数据库
    # TODO: 初始化交易执行通道
    # TODO: 初始化定时任务调度器
    yield
    # ---- 关闭 ----
    print("🐉 来财 (Attract-wealth) 已关闭")


app = FastAPI(
    title="来财 (Attract-wealth)",
    description="AI 驱动量化交易客户端 — 融合 8 大开源项目",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============ 路由注册 ============

@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {
        "status": "ok",
        "service": "attract-wealth",
        "version": "0.1.0",
    }


@app.get("/api/system/info")
async def system_info():
    """系统信息"""
    return {
        "name": "来财 (Attract-wealth)",
        "version": "0.1.0",
        "trading_channel": os.getenv("TRADING_CHANNEL", "simulation"),
        "llm_provider": os.getenv("LLM_BASE_URL", "未配置"),
        "llm_model": os.getenv("LLM_MODEL", "未配置"),
    }


# TODO: 注册子路由
# from src.routers import trading, analysis, strategy, data, evolution, system, auth
# app.include_router(trading.router, prefix="/api/trading", tags=["交易"])
# app.include_router(analysis.router, prefix="/api/analysis", tags=["分析"])
# app.include_router(strategy.router, prefix="/api/strategy", tags=["策略"])
# app.include_router(data.router, prefix="/api/data", tags=["数据"])
# app.include_router(evolution.router, prefix="/api/evolution", tags=["进化"])
# app.include_router(system.router, prefix="/api/system", tags=["系统"])

# 静态文件 (前端 build 产物)
frontend_dist = os.path.join(os.path.dirname(__file__), "frontend", "dist")
if os.path.isdir(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")


def cli_entry():
    """CLI 入口点"""
    import uvicorn
    uvicorn.run(
        "src.main:app",
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", "8000")),
        reload=os.getenv("DEBUG", "false").lower() == "true",
    )


if __name__ == "__main__":
    cli_entry()
