import asyncio
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.log_context import log_context, room_log_fields
from app.core.logger import get_logger
from app.models import LiveRoom
from app.modules.observability.diagnostics import HARDWARE_ENCODERS, capture, diagnose, diagnostic_archive, issues
from app.modules.observability.redaction import export_safe, redact
from app.modules.recording.status import get_recording_status
from app.services.platforms.recorder import get_ffmpeg_path
from app.services.platforms.recorder_factory import create_recorder
from app.shared.filesystem.access import check_directory_access


logger = get_logger(__name__)


def local_access(request: Request):
    try:
        check_directory_access(request)
    except HTTPException as exc:
        raise HTTPException(status_code=403, detail="运行日志与故障诊断仅允许从后端本机页面访问") from exc


router = APIRouter(prefix="/api/system", tags=["运行日志与诊断"], dependencies=[Depends(local_access)])


class LogFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    room_id: int | None = Field(default=None, ge=1)
    recording_log_id: int | None = Field(default=None, ge=1)
    processing_job_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    platform: Literal["DOUYIN", "BILIBILI", "DOUYU"] | None = None
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] | None = None
    keyword: str | None = Field(default=None, max_length=200)
    start: datetime | None = None
    end: datetime | None = None
    before: str | None = Field(default=None, pattern=r"^\d{20}-[a-f0-9]{8}$")
    after: str | None = Field(default=None, pattern=r"^\d{20}-[a-f0-9]{8}$")
    limit: int = Field(default=200, ge=1, le=500)

    @model_validator(mode="after")
    def validate_range(self):
        for field in ("start", "end"):
            value = getattr(self, field)
            if value is not None:
                setattr(self, field, value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc))
        if self.start and self.end and self.start > self.end:
            raise ValueError("开始时间不能晚于结束时间")
        if self.before and self.after:
            raise ValueError("不能同时使用前后游标")
        return self

    def arguments(self):
        result = self.model_dump()
        for field in ("start", "end"):
            if result[field] is not None:
                result[field] = result[field].isoformat()
        return result


class DiagnosticOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    test_write: bool = Field(default=False, strict=True)


class EncoderOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    encoder: str = Field(min_length=1, max_length=64)


def store_for(request):
    store = getattr(request.app.state, "runtime_logs", None)
    if store is None:
        raise HTTPException(status_code=503, detail="运行日志服务尚未启动")
    return store


def diagnostic_lock(request):
    lock = getattr(request.app.state, "diagnostics_lock", None)
    if lock is None:
        request.app.state.diagnostics_lock = lock = asyncio.Lock()
    if lock.locked():
        raise HTTPException(status_code=409, detail="已有诊断正在执行，请稍后重试")
    return lock


@router.get("/logs")
async def runtime_logs(request: Request, filters: Annotated[LogFilters, Query()]):
    result = await asyncio.to_thread(store_for(request).query, **filters.arguments())
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@router.get("/issues")
async def recent_issues(request: Request, room_id: int | None = Query(default=None, ge=1)):
    result = await asyncio.to_thread(issues, store_for(request), room_id)
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@router.post("/diagnostics")
async def run_diagnostics(payload: DiagnosticOptions, request: Request):
    store = store_for(request)
    async with diagnostic_lock(request):
        report = export_safe(await diagnose(request.app, store, payload.test_write), [], store.secrets)
        request.app.state.last_diagnostics = report
        logger.info("环境诊断完成")
        return JSONResponse(report, headers={"Cache-Control": "no-store"})


@router.post("/diagnostics/platform/{room_id}")
async def platform_diagnostic(room_id: int, request: Request):
    store = store_for(request)
    async with diagnostic_lock(request):
        async with request.app.state.db() as db:
            room = await db.get(LiveRoom, room_id)
            if room is None or room.del_flag:
                raise HTTPException(status_code=404, detail="直播间不存在")
            fields = {column.name: getattr(room, column.name) for column in LiveRoom.__table__.columns}
        with log_context(**room_log_fields(fields)):
            try:
                recorder = create_recorder(request.app, fields)
                if recorder is None:
                    raise ValueError("不支持的平台")
                result = await asyncio.wait_for(recorder.check_live_status(), timeout=20)
                logger.info("平台连接测试成功，当前%s", "开播" if result.get("is_live") else "未开播")
                return {"status": "ok", "detail": "平台检查请求完成，当前" + ("开播" if result.get("is_live") else "未开播")}
            except Exception as exc:
                logger.warning("平台连接测试失败: %s", exc, extra={"event_code": "live_check"})
                return {"status": "failed", "detail": redact(str(exc) or "平台检查超时", store.secrets)}


@router.post("/diagnostics/encoder")
async def encoder_diagnostic(payload: EncoderOptions, request: Request):
    store = store_for(request)
    if payload.encoder not in HARDWARE_ENCODERS:
        raise HTTPException(status_code=400, detail="仅支持列表中的硬件编码器")
    async with diagnostic_lock(request):
        try:
            await capture([get_ffmpeg_path(), "-v", "error", "-nostdin", "-f", "lavfi", "-i", "color=c=black:s=320x240:r=10:d=0.2",
                           "-an", "-c:v", payload.encoder, "-f", "null", "-"], timeout=8)
            return {"status": "ok", "detail": "硬件编码器实际编码测试通过"}
        except Exception as exc:
            return {"status": "failed", "detail": redact(str(exc) or "硬件编码测试超时", store.secrets)}


@router.post("/diagnostics/export")
async def export_diagnostics(payload: LogFilters, request: Request):
    store = store_for(request)
    data = payload.arguments()
    archive = await asyncio.to_thread(diagnostic_archive, request.app, store, data,
                                      get_recording_status(request.app).snapshot())
    return Response(archive, media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="LiveRecorder-diagnostics.zip"', "Cache-Control": "no-store"})
