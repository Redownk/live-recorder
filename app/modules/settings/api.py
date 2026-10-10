from datetime import datetime
import asyncio

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app.modules.settings.service import RecordingOptions, build_filename, resolve_save_path
from app.shared.filesystem.browser import list_directories
from app.shared.filesystem.access import check_directory_access


router = APIRouter(prefix="/api/settings", tags=["录制设置"])


@router.get("/directories")
async def browse_directories(request: Request, path: str | None = Query(default=None, max_length=1024), offset: int = Query(default=0, ge=0, le=1000000), limit: int = Query(default=200, ge=1, le=500)):
    check_directory_access(request)
    try:
        result = await asyncio.to_thread(list_directories, path, offset, limit)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="没有权限访问此目录") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="目录不存在或不是文件夹") from exc
    except (OSError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail="无法浏览此目录，请检查路径和访问权限") from exc
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


class RecordingSettingsResponse(RecordingOptions):
    resolved_save_path: str
    filename_example: str


def settings_response(options: RecordingOptions):
    return RecordingSettingsResponse(
        **options.model_dump(),
        resolved_save_path=str(resolve_save_path(options.save_path)),
        filename_example=build_filename(
            options.filename_template,
            {"platform": "DOUYIN", "room_id": "123456", "owner": "示例主播", "remark": "示例备注"},
            {"owner": "示例主播", "title": "直播标题"},
            datetime(2026, 1, 1, 12, 0, 0),
            "a1b2c3d4" * 4,
        ) + ".ts",
    )


@router.get("", response_model=RecordingSettingsResponse)
async def get_settings(request: Request):
    return settings_response(request.app.state.recording_settings.settings)


@router.put("", response_model=RecordingSettingsResponse)
async def update_settings(payload: RecordingOptions, request: Request):
    try:
        await request.app.state.recording_settings.save(request.app, payload)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="保存目录不可用，请检查路径和写入权限") from exc
    return settings_response(payload)


@router.post("/preview", response_model=RecordingSettingsResponse)
async def preview_settings(payload: RecordingOptions):
    return settings_response(payload)
