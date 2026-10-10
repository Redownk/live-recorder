import asyncio

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app.shared.filesystem.access import check_directory_access
from app.shared.filesystem.browser import list_directories
from app.modules.video_processing.schemas import ProcessingOptions


router = APIRouter(prefix="/api/processing", tags=["视频处理"])


@router.get("/files")
async def browse_files(request: Request, path: str | None = Query(default=None, max_length=1024), offset: int = Query(default=0, ge=0, le=1000000), limit: int = Query(default=200, ge=1, le=500)):
    check_directory_access(request)
    try:
        data = await asyncio.to_thread(list_directories, path, offset, limit, True)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="没有权限访问此目录") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="目录不存在或不是文件夹") from exc
    except (OSError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail="无法浏览此目录，请检查路径和访问权限") from exc
    return JSONResponse(data, headers={"Cache-Control": "no-store"})


@router.get("/capabilities")
async def capabilities(request: Request):
    check_directory_access(request)
    return await request.app.state.video_processing.capabilities()


@router.get("/jobs")
async def list_jobs(request: Request):
    check_directory_access(request)
    return JSONResponse(list(reversed(request.app.state.video_processing.jobs.values())), headers={"Cache-Control": "no-store"})


@router.post("/jobs", status_code=202)
async def create_job(options: ProcessingOptions, request: Request):
    check_directory_access(request)
    try:
        return request.app.state.video_processing.submit(options)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/jobs/{job_id}")
async def cancel_job(job_id: str, request: Request):
    check_directory_access(request)
    manager = request.app.state.video_processing
    if job_id not in manager.jobs:
        raise HTTPException(status_code=404, detail="处理任务不存在")
    await manager.cancel(job_id)
    return manager.jobs[job_id]
