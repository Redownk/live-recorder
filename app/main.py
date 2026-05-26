import asyncio
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import crawler_api, live, rooms
from app.core.config import local_config
from app.core.database import init_db
from app.core.logger import get_logger, setup_logging
from app.core.redis_client import create_redis_client
from app.services.crawler_manager import crawler_manager


setup_logging()
logger = get_logger(__name__)

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

app = FastAPI(title="Live Recorder", description="多直播平台单体录制平台")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")

app.include_router(rooms.router)
app.include_router(live.router)
app.include_router(crawler_api.router)


@app.on_event("startup")
async def startup_event():
    logger.info("服务启动中...")
    await init_db(app, local_config.get("database", {}).get("url", "sqlite+aiosqlite:///./data/live_recorder.db"))

    app.state.redis = None
    app.state.redis_connected = False
    try:
        app.state.redis = await create_redis_client()
        await app.state.redis.ping()
        app.state.redis_connected = True
        logger.info("Redis连接成功")
    except Exception as exc:
        logger.warning("Redis连接失败，录制监控暂不可用: %s", exc)

    crawler_manager.init_app(app)
    if local_config.get("crawler", {}).get("auto_start", False):
        await crawler_manager.start()

    logger.info("服务启动完成")


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("服务关闭中...")
    await crawler_manager.stop()

    redis_client = getattr(app.state, "redis", None)
    if redis_client is not None:
        await redis_client.aclose()

    engine = getattr(app.state, "engine", None)
    if engine is not None:
        await engine.dispose()

    logger.info("服务关闭完成")


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(static_dir / "index.html")


@app.get("/actuator/health")
async def health():
    return {
        "status": "UP",
        "components": {
            "database": "UP",
            "redis": "UP" if getattr(app.state, "redis_connected", False) else "DOWN",
        },
    }


if __name__ == "__main__":
    import uvicorn

    service_config = local_config.get("service", {})
    uvicorn.run(
        app,
        host=service_config.get("host", "0.0.0.0"),
        port=int(service_config.get("port", 8000)),
    )
