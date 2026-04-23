"""
FastAPI entry for LaiCai.
"""
from __future__ import annotations

import logging
import os
import sys
import traceback
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Import Routers (Must be imported before usage)
from src.routers import trading, system, strategy, monitor, stream

from src.core.autopilot_templates import load_autopilot_templates
from src.core.event_engine import EventEngine
from src.core.startup_preflight import run_startup_preflight
from src.core.storage import init_all_databases
from src.core.strategy_store import StrategyStore
from src.core.system_store import SystemStore
from src.core.ths_bridge_runtime import THSBridgeRuntime
from src.core.trading_service import TradingService
from src.core.errors import ok_response
from src.evolution.backtest_runner import BacktestRunner
from src.services.dataflow_service import DataflowService

# Determine base path for resources
if hasattr(sys, "_MEIPASS"):
    # PyInstaller bundled environment
    BASE_DIR = Path(sys._MEIPASS)
else:
    # Development environment
    BASE_DIR = Path(__file__).parent.parent

load_dotenv()

# Initialize logging to both console and file
log_dir = Path(os.getenv("LOG_DIR", os.path.join(os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(__file__).split("src")[0], "logs")))
log_dir.mkdir(parents=True, exist_ok=True)
log_file = log_dir / "laicai_startup.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file, encoding="utf-8")
    ]
)
logger = logging.getLogger(__name__)
logger.info("来财 (LaiCai) 启动中... (Frozen: %s)", getattr(sys, 'frozen', False))


def _is_true(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_watchlist() -> list[str]:
    raw = os.getenv("WATCHLIST", "000001,300059")
    return [item.strip() for item in raw.split(",") if item.strip()]


def _setup_legacy_schedule(event_engine: EventEngine):
    interval_minutes = int(os.getenv("AUTO_POLLING_MINUTES", "0"))
    if interval_minutes > 0:
        event_engine.add_interval_trigger(interval_minutes)

    tail_attack = os.getenv("TAIL_ATTACK_TIME", "").strip()
    if tail_attack:
        parsed = event_engine._parse_time(tail_attack)  # noqa: SLF001
        if parsed:
            event_engine.add_tail_attack_trigger(hour=parsed["hour"], minute=parsed["minute"])

    day_roll = os.getenv("DAY_ROLL_TIME", "").strip()
    if day_roll:
        parsed = event_engine._parse_time(day_roll)  # noqa: SLF001
        if parsed:
            event_engine.add_day_roll_trigger(hour=parsed["hour"], minute=parsed["minute"])


@asynccontextmanager
async def lifespan(app: FastAPI):
    channel = os.getenv("TRADING_CHANNEL", "ths_auto").strip().lower()
    include_stability_probe = _is_true(os.getenv("STARTUP_PREFLIGHT_INCLUDE_STABILITY"), default=False)
    strict_preflight = _is_true(os.getenv("STARTUP_STRICT_PREFLIGHT"), default=False)

    bridge_runtime = THSBridgeRuntime()
    event_engine: EventEngine | None = None
    trading_service: TradingService | None = None

    try:
        app.state.ths_bridge_runtime = bridge_runtime
        app.state.ths_bridge = bridge_runtime.start(channel=channel)

        if channel == "ths_auto":
            from src.execution.ths_auto import probe_easytrader_readiness
            logger.info("正在探测 ths_auto 通道就绪状态...")
            probe = probe_easytrader_readiness()
            app.state.ths_auto_probe = probe
            if not probe.get("ok", False):
                logger.warning("ths_auto 通道未完全就绪: %s", probe.get("message", "unknown"))

        preflight_report = run_startup_preflight(channel=channel, include_stability_probe=include_stability_probe)
        app.state.startup_preflight = preflight_report
        if not preflight_report.get("ok", False):
            logger.warning("startup preflight has critical failures: %s", preflight_report.get("summary", {}))
            if strict_preflight:
                raise RuntimeError("startup preflight failed in strict mode")

        init_all_databases()
        trading_service = TradingService(trading_channel=channel, event_publisher=stream)
        await trading_service.initialize()

        system_store = SystemStore()
        dataflow_service = DataflowService()
        app.state.dataflow_service = dataflow_service
        try:
            app.state.dataflow_provider_restore = dataflow_service.apply_persisted_provider(system_store)
        except Exception as exc:  # noqa: BLE001
            logger.warning("failed to apply persisted dataflow provider: %s", exc)
            app.state.dataflow_provider_restore = {"applied": False, "reason": str(exc)}

        persisted_llm_config = system_store.get_setting("llm_runtime_config", {})
        if isinstance(persisted_llm_config, dict) and persisted_llm_config:
            try:
                trading_service.update_llm_runtime_config(persisted_llm_config, operator="startup")
            except Exception as exc:  # noqa: BLE001
                logger.warning("failed to apply persisted llm runtime config: %s", exc)
        event_engine = EventEngine(
            runner=trading_service,
            execute_orders=os.getenv("AUTO_EXECUTE_ORDERS", "true").lower() == "true",
            system_store=system_store,
            autopilot_templates=load_autopilot_templates(),
        )
        event_engine.restore_watchlists(_parse_watchlist())

        template_name = os.getenv("AUTOPILOT_TEMPLATE", "").strip() or system_store.get_autopilot_template(default="")
        if template_name:
            try:
                event_engine.apply_autopilot_template(template_name, persist=True)
            except ValueError as exc:
                logger.warning("autopilot template load failed, fallback to legacy schedule: %s", exc)
                _setup_legacy_schedule(event_engine)
        else:
            _setup_legacy_schedule(event_engine)

        event_engine.start()
        app.state.trading_service = trading_service
        app.state.event_engine = event_engine
        app.state.system_store = system_store
        app.state.strategy_store = StrategyStore()
        app.state.backtest_runner = BacktestRunner()
        yield
    finally:
        if event_engine is not None:
            try:
                event_engine.stop()
            except Exception:  # noqa: BLE001
                pass
        if trading_service is not None:
            try:
                await trading_service.shutdown()
            except (BaseException,):  # noqa: BLE001 — CancelledError is BaseException in 3.9+
                pass
        try:
            app.state.ths_bridge = bridge_runtime.stop(reason="app_shutdown")
        except Exception:  # noqa: BLE001
            pass
        app.state.ths_bridge_runtime = None


app = FastAPI(
    title="来财 (Attract-wealth)",
    description="AI 驱动量化交易客户端",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health_check():
    return ok_response(
        {
            "status": "ok",
            "service": "attract-wealth",
            "version": "0.1.0",
        },
        code="HEALTH_OK",
    )


@app.get("/api/system/info")
async def system_info():
    preflight: dict[str, Any] = getattr(app.state, "startup_preflight", {})
    ths_bridge: dict[str, Any] = getattr(app.state, "ths_bridge", {})
    return ok_response(
        {
            "name": "来财 (Attract-wealth)",
            "version": "0.1.0",
            "trading_channel": os.getenv("TRADING_CHANNEL", "ths_auto"),
            "llm_provider": os.getenv("LLM_BASE_URL", "未配置"),
            "llm_model": os.getenv("LLM_MODEL", "未配置"),
            "startup_preflight_ok": preflight.get("ok", False),
            "startup_preflight_summary": preflight.get("summary", {}),
            "ths_bridge": ths_bridge,
        },
        code="SYSTEM_INFO_OK",
    )


app.include_router(trading.router, prefix="/api/trading", tags=["trading"])
app.include_router(system.router, prefix="/api/system", tags=["system"])
app.include_router(strategy.router, prefix="/api/strategy", tags=["strategy"])
app.include_router(monitor.router, prefix="/api/v1/monitor", tags=["monitor"])
app.include_router(stream.router, prefix="/api/v1/stream", tags=["stream"])

# Frontend distribution static files
if hasattr(sys, "_MEIPASS"):
    frontend_dist = os.path.join(sys._MEIPASS, "frontend", "dist")
else:
    frontend_dist = os.path.join(os.path.dirname(__file__), "frontend", "dist")

if os.path.isdir(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")


def cli_entry():
    import uvicorn

    try:
        host = os.getenv("API_HOST", "0.0.0.0")
        port = int(os.getenv("API_PORT", "8000"))
        reload = os.getenv("DEBUG", "false").lower() == "true"

        # When running in bundled environment, we should use the app object directly
        # and disable reload (since uvicorn's reload doesn't work well with PyInstaller)
        if hasattr(sys, "_MEIPASS"):
            uvicorn.run(
                app,
                host=host,
                port=port,
                reload=False,
            )
        else:
            uvicorn.run(
                "src.main:app",
                host=host,
                port=port,
                reload=reload,
            )
    except Exception:
        print("\n" + "=" * 60)
        print("CRITICAL STARTUP ERROR")
        print("=" * 60)
        traceback.print_exc()
        print("=" * 60)
        print("Press Enter to exit...")
        input()
        sys.exit(1)


if __name__ == "__main__":
    cli_entry()
