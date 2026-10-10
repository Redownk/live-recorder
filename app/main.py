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
from app.core.config import local_config
from app.core.database import init_db, resolve_database_url
from app.core.paths import RESOURCE_DIR
from app.core.logger import get_logger, setup_logging
from app.core.instance_lock import InstanceLock
from app.modules.recording.crawler import crawler_manager
from app.modules.settings.service import init_recording_settings
from app.modules.recording.status import RecordingStatusTracker
from app.modules.recording.tasks import RecordingTaskManager, get_recording_tasks
from app.modules.recording.recovery import recover_interrupted_recordings
from app.modules.video_processing.service import VideoProcessingManager


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


@app.on_event("startup")
async def startup_event():
    logger.info("服务启动中...")
    db_url = resolve_database_url(local_config.get("database", {}).get("url", "sqlite+aiosqlite:///./data/live_recorder.db"))
    instance_lock = InstanceLock(db_url)
    instance_lock.acquire()
    app.state.instance_lock = instance_lock
    try:
        await init_db(app, db_url)
        await init_recording_settings(app)
        app.state.recording_status = RecordingStatusTracker()
        app.state.recording_tasks = RecordingTaskManager()
        app.state.video_processing = VideoProcessingManager(app.state.recording_tasks)
        await recover_interrupted_recordings(app)
        crawler_manager.init_app(app)
        if local_config.get("crawler", {}).get("auto_start", False):
            await crawler_manager.start()
    except BaseException:
        engine = getattr(app.state, "engine", None)
        if engine is not None:
            await engine.dispose()
        instance_lock.release()
        raise

    logger.info("服务启动完成")


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("服务关闭中...")
    tasks = get_recording_tasks(app)
    tasks.closing = True
    try:
        try:
            await crawler_manager.shutdown()
        finally:
            try:
                await tasks.shutdown()
            finally:
                await app.state.video_processing.shutdown()
        await recover_interrupted_recordings(app)
    finally:
        try:
            engine = getattr(app.state, "engine", None)
            if engine is not None:
                await engine.dispose()
        finally:
            instance_lock = getattr(app.state, "instance_lock", None)
            if instance_lock is not None:
                instance_lock.release()

    logger.info("服务关闭完成")


@app.get("/", include_in_schema=False)
async def index():
    frontend_index = RESOURCE_DIR / "frontend" / "dist" / "index.html"
    if frontend_index.is_file():
        return FileResponse(frontend_index, headers={"Cache-Control": "no-cache"})
    return {"name": "Live Recorder API", "docs": "/docs"}


@app.get("/actuator/health")
async def health():
    return {
        "status": "UP",
        "components": {
            "database": "UP",
        },
    }


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
