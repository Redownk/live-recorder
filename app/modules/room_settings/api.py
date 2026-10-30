import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.session import get_db
from app.core.logger import get_logger
from app.models import RoomRecordingSettings
from app.modules.live_rooms.api import get_room
from app.modules.room_settings.schemas import RoomRecordingOverrides
from app.modules.settings.service import RecordingOptions, build_filename, ensure_writable_directory, resolve_save_path


router = APIRouter(prefix="/api/rooms", tags=["房间录制设置"])
logger = get_logger(__name__)


def response_for(room, overrides, manager):
    effective = RecordingOptions.model_validate({**manager.settings.model_dump(), **overrides.model_dump(exclude_none=True)})
    fields = {column.name: getattr(room, column.name) for column in room.__table__.columns}
    return {"room_id": room.id, "overrides": overrides.model_dump(), "effective": effective.model_dump(),
            "global_settings": manager.settings.model_dump(), "customized": bool(overrides.model_dump(exclude_none=True)),
            "resolved_save_path": str(resolve_save_path(effective.save_path)),
            "filename_example": build_filename(effective.filename_template, fields, {"owner": room.owner, "title": room.title}, datetime(2026, 1, 1, 12), "a1b2c3d4" * 4) + ".ts"}


@router.get("/{room_id}/recording-settings")
async def get_room_settings(room_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    room = await get_room(room_id, db)
    manager = request.app.state.recording_settings
    return response_for(room, RoomRecordingOverrides(**manager.room_overrides.get(room_id, {})), manager)


@router.post("/{room_id}/recording-settings/preview")
async def preview_room_settings(room_id: int, payload: RoomRecordingOverrides, request: Request, db: AsyncSession = Depends(get_db)):
    return response_for(await get_room(room_id, db), payload, request.app.state.recording_settings)


async def persist(room_id, payload, request, db):
    manager = request.app.state.recording_settings
    async with manager.write_lock:
        room = await get_room(room_id, db)
        values = payload.model_dump(exclude_none=True)
        if "save_path" in values:
            try:
                await asyncio.to_thread(ensure_writable_directory, resolve_save_path(values["save_path"]))
            except (OSError, ValueError) as exc:
                raise HTTPException(status_code=400, detail="房间保存目录不可用，请检查路径和写入权限") from exc
        record = await db.get(RoomRecordingSettings, room_id)
        if not values:
            if record is not None:
                await db.delete(record)
        else:
            if record is None:
                record = RoomRecordingSettings(room_id=room_id)
                db.add(record)
            for key, value in payload.model_dump().items():
                setattr(record, key, value)
        await db.commit()
        if values:
            manager.room_overrides[room_id] = values
        else:
            manager.room_overrides.pop(room_id, None)
        manager.touch_room(room_id)
        logger.info("房间独立录制设置%s", "已保存" if values else "已恢复继承全局",
                    extra={"room_id": room_id, "platform": room.platform, "platform_room_id": str(room.room_id)})
        return response_for(room, payload, manager)


@router.put("/{room_id}/recording-settings")
async def save_room_settings(room_id: int, payload: RoomRecordingOverrides, request: Request, db: AsyncSession = Depends(get_db)):
    return await persist(room_id, payload, request, db)


@router.delete("/{room_id}/recording-settings")
async def reset_room_settings(room_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    return await persist(room_id, RoomRecordingOverrides(), request, db)
