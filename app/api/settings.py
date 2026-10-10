from datetime import datetime

from fastapi import APIRouter, HTTPException, Request

from app.services.recording_settings import RecordingOptions, build_filename, resolve_save_path


router = APIRouter(prefix="/api/settings", tags=["录制设置"])


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
