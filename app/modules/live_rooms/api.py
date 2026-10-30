from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.session import get_db
from app.models import LiveRoom, LiveRoomLog, LiveRoomLogVideo, LiveRoomStats, RoomRecordingSettings
from app.modules.live_rooms.schemas import LiveRoomCreate, LiveRoomOut, LiveRoomUpdate, MonitorUpdate, RecordingStop
from app.modules.live_rooms.checker import LiveChecker
from app.services.platforms.recorder_factory import create_recorder
from app.modules.recording.status import get_recording_status
from app.modules.recording.tasks import get_recording_tasks
from app.modules.recording.disk import DiskSpaceError
from app.core.log_context import log_context, room_log_fields
from app.core.logger import get_logger


router = APIRouter(prefix="/api", tags=["录制管理"])
logger = get_logger(__name__)


def normalize_platform(platform: str) -> str:
    value = platform.strip().upper()
    if value not in {"DOUYIN", "BILIBILI", "DOUYU"}:
        raise HTTPException(status_code=400, detail="platform 仅支持 DOUYIN / BILIBILI / DOUYU")
    return value


@router.get("/rooms", response_model=list[LiveRoomOut])
async def list_rooms(keyword: str | None = Query(default=None), db: AsyncSession = Depends(get_db)):
    stmt = select(LiveRoom).where(LiveRoom.del_flag == 0).order_by(desc(LiveRoom.id))
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            or_(
                LiveRoom.room_id.like(like),
                LiveRoom.owner.like(like),
                LiveRoom.remark.like(like),
                LiveRoom.title.like(like),
                LiveRoom.platform.like(like),
            )
        )
    result = await db.execute(stmt)
    rooms = result.scalars().all()
    customized = set((await db.execute(select(RoomRecordingSettings.room_id))).scalars().all())
    for room in rooms:
        room.recording_settings_customized = room.id in customized
    return rooms


@router.get("/recording-status")
async def recording_status(request: Request):
    controls = get_recording_tasks(request.app).control_snapshot()
    for room_id, session in get_recording_status(request.app).snapshot().items():
        if controls.get(room_id, {}).get("state") != "stopping":
            controls[room_id] = session
    return controls


@router.post("/rooms", response_model=LiveRoomOut, status_code=status.HTTP_201_CREATED)
async def create_room(payload: LiveRoomCreate, request: Request, db: AsyncSession = Depends(get_db)):
    try:
        info = await LiveChecker.check(payload.room_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"直播间信息获取失败: {exc}") from exc

    if not isinstance(info, dict) or info.get("result") != "success":
        raise HTTPException(status_code=400, detail="直播间信息获取失败，请检查链接是否有效")

    room_id = info.get("roomId")
    platform = info.get("platform")
    if not room_id or not platform:
        raise HTTPException(status_code=400, detail="checker 未返回平台或房间号")

    room = LiveRoom(
        platform=normalize_platform(platform),
        room_id=str(room_id),
        room_url=payload.room_url,
        sec_uid=str(info.get("secUid") or "") or None,
        owner=info.get("owner"),
        remark=(payload.remark or "").strip() or info.get("owner"),
        title=info.get("roomTitle") or info.get("title") or info.get("owner"),
        avatar=info.get("avatar"),
        cover=info.get("cover"),
        monitor_enabled=payload.monitor_enabled,
    )
    db.add(room)
    await db.commit()
    await db.refresh(room)
    request.app.state.recording_settings.touch_room(room.id)
    logger.info("直播间已添加，监控%s", "已启用" if room.monitor_enabled else "已暂停", extra=room_log_fields({"id": room.id, "platform": room.platform, "room_id": room.room_id}))
    return room


@router.get("/rooms/{room_id}", response_model=LiveRoomOut)
async def get_room(room_id: int, db: AsyncSession = Depends(get_db)):
    room = await db.get(LiveRoom, room_id)
    if room is None or room.del_flag != 0:
        raise HTTPException(status_code=404, detail="直播间不存在")
    room.recording_settings_customized = await db.get(RoomRecordingSettings, room.id) is not None
    return room


async def refresh_control_room(room, db, key):
    await db.refresh(room)
    if room.del_flag != 0:
        raise HTTPException(status_code=404, detail="直播间不存在")
    if (room.platform, str(room.room_id)) != key:
        raise HTTPException(status_code=409, detail="直播间信息已变化，请刷新后重试")


@router.put("/rooms/{room_id}", response_model=LiveRoomOut)
async def update_room(room_id: int, payload: LiveRoomUpdate, request: Request, db: AsyncSession = Depends(get_db)):
    room = await get_room(room_id, db)
    data = payload.model_dump(exclude_unset=True)
    if "platform" in data and data["platform"] is not None:
        data["platform"] = normalize_platform(data["platform"])
    manager = get_recording_tasks(request.app)
    key = (room.platform, str(room.room_id))
    async with manager.control_lock(key):
        await refresh_control_room(room, db, key)
        was_monitoring = room.monitor_enabled
        identity_changed = any(name in data and data[name] != getattr(room, name) for name in ("platform", "room_id"))
        if identity_changed and (manager.is_recording(key) or key in manager.checks):
            raise HTTPException(status_code=409, detail="请先停止该直播间录制，再修改平台或房间号")
        for name, value in data.items():
            setattr(room, name, value)
        await db.commit()
        if (was_monitoring and data.get("monitor_enabled") is False) or identity_changed:
            manager.disabled_keys.add(key)
            await manager.stop_room(key)
        if room.monitor_enabled:
            manager.disabled_keys.discard((room.platform, str(room.room_id)))
            if data.get("monitor_enabled") is True:
                manager.notices.pop((room.platform, str(room.room_id)), None)
                request.app.state.recording_settings.touch_room(room.id)
    await db.refresh(room)
    return room


@router.patch("/rooms/{room_id}/monitor", response_model=LiveRoomOut)
async def update_monitor(room_id: int, payload: MonitorUpdate, request: Request, db: AsyncSession = Depends(get_db)):
    room = await get_room(room_id, db)
    manager = get_recording_tasks(request.app)
    key = (room.platform, str(room.room_id))
    async with manager.control_lock(key):
        await refresh_control_room(room, db, key)
        room.monitor_enabled = payload.monitor_enabled
        await db.commit()
        if payload.monitor_enabled:
            manager.disabled_keys.discard(key)
            manager.notices.pop(key, None)
            request.app.state.recording_settings.touch_room(room.id)
        else:
            manager.disabled_keys.add(key)
            await manager.stop_room(key)
    await db.refresh(room)
    logger.info("房间监控%s", "已启用" if room.monitor_enabled else "已暂停",
                extra={"room_id": room.id, "platform": room.platform, "platform_room_id": str(room.room_id)})
    return room


@router.post("/rooms/{room_id}/recording/start")
async def start_room_recording(room_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    room = await get_room(room_id, db)
    manager = get_recording_tasks(request.app)
    key = (room.platform, str(room.room_id))
    async with manager.control_lock(key):
        await refresh_control_room(room, db, key)
        recorder = create_recorder(request.app, {column.name: getattr(room, column.name) for column in LiveRoom.__table__.columns})
        if recorder is None:
            raise HTTPException(status_code=400, detail="不支持的平台")
        token = manager.begin_check(key, manual=True)
        if token is None:
            raise HTTPException(status_code=409, detail="该房间已有检查或录制任务，或服务正在停止")
    try:
        return await recorder.start(manual=True, token=token)
    except DiskSpaceError as exc:
        raise HTTPException(status_code=507, detail=str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="检查直播状态超时") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="检查直播状态失败，请检查平台配置和运行日志") from exc


@router.post("/rooms/{room_id}/recording/stop")
async def stop_room_recording(room_id: int, payload: RecordingStop, request: Request, db: AsyncSession = Depends(get_db)):
    room = await get_room(room_id, db)
    manager = get_recording_tasks(request.app)
    key = (room.platform, str(room.room_id))
    async with manager.control_lock(key):
        await refresh_control_room(room, db, key)
        if payload.disable_monitor:
            room.monitor_enabled = False
            await db.commit()
            manager.disabled_keys.add(key)
        await manager.stop_room(key)
        logger.info("手动停止本次录制，%s", "暂停监控" if payload.disable_monitor else "保留监控",
                    extra={"room_id": room.id, "platform": room.platform, "platform_room_id": str(room.room_id)})
    return {"status": "stopped", "monitor_enabled": room.monitor_enabled}


@router.get("/rooms/{room_id}/live-status")
async def check_room_live_status(room_id: int, db: AsyncSession = Depends(get_db)):
    room = await get_room(room_id, db)
    recorder = create_recorder(None, {
        "id": room.id,
        "platform": room.platform,
        "room_id": room.room_id,
        "sec_uid": room.sec_uid,
    })
    if recorder is None:
        raise HTTPException(status_code=400, detail="不支持的平台")
    with log_context(room_id=room.id, platform=room.platform, platform_room_id=str(room.room_id)):
        try:
            result = await recorder.check_live_status()
            logger.info("手动检查直播状态：%s", "开播" if result.get("is_live") else "未开播")
            return result
        except Exception:
            logger.exception("手动检查直播状态失败", extra={"event_code": "live_check"})
            raise


@router.delete("/rooms/{room_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_room(room_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    room = await get_room(room_id, db)
    manager = get_recording_tasks(request.app)
    key = (room.platform, str(room.room_id))
    async with manager.control_lock(key):
        await refresh_control_room(room, db, key)
        room.del_flag = 1
        await db.commit()
        manager.disabled_keys.add(key)
        await manager.stop_room(key)
        settings = request.app.state.recording_settings
        async with settings.write_lock:
            overrides = await db.get(RoomRecordingSettings, room_id)
            if overrides is not None:
                await db.delete(overrides)
                await db.commit()
            settings.room_overrides.pop(room_id, None)
            settings.touch_room(room_id)


@router.get("/logs")
async def list_logs(room_id: int | None = Query(default=None), limit: int = Query(default=50, ge=1, le=200), db: AsyncSession = Depends(get_db)):
    stmt = select(LiveRoomLog).where(LiveRoomLog.del_flag == 0).order_by(desc(LiveRoomLog.id)).limit(limit)
    if room_id is not None:
        stmt = stmt.where(LiveRoomLog.live_room_id == room_id)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/videos")
async def list_videos(log_id: int | None = Query(default=None), limit: int = Query(default=50, ge=1, le=200), db: AsyncSession = Depends(get_db)):
    stmt = select(LiveRoomLogVideo).where(LiveRoomLogVideo.del_flag == 0).order_by(desc(LiveRoomLogVideo.id)).limit(limit)
    if log_id is not None:
        stmt = stmt.where(LiveRoomLogVideo.live_room_log_id == log_id)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/videos/{video_id}/file")
async def get_video_file(video_id: int, db: AsyncSession = Depends(get_db)):
    video = await db.get(LiveRoomLogVideo, video_id)
    if video is None or video.del_flag != 0 or not video.file_path:
        raise HTTPException(status_code=404, detail="本地视频不存在")
    path = Path(video.file_path)
    if not path.is_absolute() or not path.is_file():
        raise HTTPException(status_code=404, detail="本地视频文件已移动或删除")
    media_type = {".ts": "video/mp2t", ".flv": "video/x-flv", ".mp4": "video/mp4"}.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media_type, filename=video.file_name, content_disposition_type="inline")


@router.get("/stats")
async def list_stats(log_id: int, limit: int = Query(default=100, ge=1, le=500), db: AsyncSession = Depends(get_db)):
    stmt = (
        select(LiveRoomStats)
        .where(LiveRoomStats.live_room_log_id == log_id)
        .order_by(desc(LiveRoomStats.id))
        .limit(limit)
    )
    result = await db.execute(stmt)
    return result.scalars().all()
