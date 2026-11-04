"""创建 FastAPI 应用、注册路由，并协调数据库、后台任务和日志的启动与关闭。"""


import asyncio
import os
import sys

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.modules.recording import api as crawler_api
from app.modules.live_rooms import api as rooms, live_api as live
from app.modules.settings import api as settings
from app.modules.video_processing import api as processing
from app.modules.observability import api as observability
from app.modules.room_settings import api as room_settings
from app.core.config import local_config
from app.core.database import init_db, resolve_database_url
from app.core.paths import RESOURCE_DIR
from app.core.logger import get_logger, setup_logging, start_runtime_logging, stop_runtime_logging
from app.core.instance_lock import InstanceLock
from app.modules.recording.crawler import crawler_manager
from app.modules.settings.service import init_recording_settings
from app.modules.recording.status import RecordingStatusTracker
from app.modules.recording.tasks import RecordingTaskManager
from app.modules.recording.recovery import recover_interrupted_recordings
from app.modules.recording.disk import get_disk_guard
from app.modules.video_processing.service import VideoProcessingManager
from app.services.platforms.common import http as platform_http


setup_logging()
logger = get_logger(__name__)

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

app = FastAPI(title="Live Recorder", description="多直播平台单体录制平台")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(rooms.router)
app.include_router(live.router)
app.include_router(crawler_api.router)
app.include_router(settings.router)
app.include_router(processing.router)
app.include_router(observability.router)
app.include_router(room_settings.router)


async def _stop_background_tasks():
    """依次停止已创建的后台任务，确保平台请求结束后才能关闭 HTTP 客户端。"""
    tasks = getattr(app.state, "recording_tasks", None)
    if tasks is not None:
        tasks.closing = True
    try:
        guard = getattr(app.state, "recording_disk_guard", None)
        if guard is not None:
            await guard.shutdown()
    finally:
        try:
            if crawler_manager.app is app:
                await crawler_manager.shutdown()
        finally:
            try:
                if tasks is not None:
                    await tasks.shutdown()
            finally:
                processing = getattr(app.state, "video_processing", None)
                if processing is not None:
                    await processing.shutdown()


@app.on_event("startup")
async def startup_event():
    db_url = resolve_database_url(local_config.get("database", {}).get("url", "sqlite+aiosqlite:///./data/live_recorder.db"))
    instance_lock = InstanceLock(db_url)
    instance_lock.acquire()
    app.state.instance_lock = instance_lock
    try:
        app.state.runtime_logs = start_runtime_logging()
        logger.info("服务启动中...")
        platform_http.start_client()
        await init_db(app, db_url)
        await init_recording_settings(app)
        app.state.recording_status = RecordingStatusTracker()
        app.state.recording_tasks = RecordingTaskManager()
        app.state.video_processing = VideoProcessingManager(app.state.recording_tasks)
        await recover_interrupted_recordings(app)
        crawler_manager.init_app(app)
        get_disk_guard(app).start()
        if local_config.get("crawler", {}).get("auto_start", False):
            await crawler_manager.start()
    except BaseException:
        logger.exception("服务启动失败")
        try:
            await _stop_background_tasks()
        finally:
            try:
                await platform_http.close_client()
            finally:
                try:
                    engine = getattr(app.state, "engine", None)
                    if engine is not None:
                        await engine.dispose()
                finally:
                    instance_lock.release()
                    await asyncio.to_thread(stop_runtime_logging)
        raise

    logger.info("服务启动完成")


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("服务关闭中...")
    try:
        await _stop_background_tasks()
        await recover_interrupted_recordings(app)
    except BaseException:
        logger.exception("服务关闭时发生异常")
        raise
    finally:
        try:
            await platform_http.close_client()
        finally:
            try:
                engine = getattr(app.state, "engine", None)
                if engine is not None:
                    await engine.dispose()
            finally:
                instance_lock = getattr(app.state, "instance_lock", None)
                try:
                    if instance_lock is not None:
                        instance_lock.release()
                finally:
                    logger.info("服务关闭清理结束")
                    await asyncio.to_thread(stop_runtime_logging)


@app.get("/", include_in_schema=False)
async def index():
    frontend_index = RESOURCE_DIR / "frontend" / "dist" / "index.html"
    if frontend_index.is_file():
        return FileResponse(frontend_index, headers={"Cache-Control": "no-cache"})
    return {"name": "Live Recorder API", "docs": "/docs"}


@app.get("/{frontend_path:path}", include_in_schema=False)
async def frontend(frontend_path: str):
    if frontend_path.split("/", 1)[0] in {"api", "crawler", "live", "actuator", "docs", "redoc", "openapi.json"}:
        raise HTTPException(status_code=404, detail="Not Found")
    directory = (RESOURCE_DIR / "frontend" / "dist").resolve()
    target = (directory / frontend_path).resolve()
    if not target.is_relative_to(directory):
        raise HTTPException(status_code=404, detail="Not Found")
    if target.is_file():
        return FileResponse(target)
    index_file = directory / "index.html"
    if target.suffix or not index_file.is_file():
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(index_file, headers={"Cache-Control": "no-cache"})


if __name__ == "__main__":
    import uvicorn

    service_config = local_config.get("service", {})
    uvicorn.run(
        app,
        host=service_config.get("host", "0.0.0.0"),
        port=int(service_config.get("port", 8000)),
        workers=1,
    )
