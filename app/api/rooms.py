from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.session import get_db
from app.models import LiveRoom, LiveRoomLog, LiveRoomLogVideo, LiveRoomStats
from app.schemas import LiveRoomCreate, LiveRoomOut, LiveRoomUpdate, MonitorUpdate
from app.services.live_checker import LiveChecker
from app.services.platforms.recorder_factory import create_recorder


router = APIRouter(prefix="/api", tags=["录制管理"])


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
                LiveRoom.title.like(like),
                LiveRoom.platform.like(like),
            )
        )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/rooms", response_model=LiveRoomOut, status_code=status.HTTP_201_CREATED)
async def create_room(payload: LiveRoomCreate, db: AsyncSession = Depends(get_db)):
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
        title=info.get("roomTitle") or info.get("title") or info.get("owner"),
        avatar=info.get("avatar"),
        cover=info.get("cover"),
        monitor_enabled=payload.monitor_enabled,
    )
    db.add(room)
    await db.commit()
    await db.refresh(room)
    return room


@router.get("/rooms/{room_id}", response_model=LiveRoomOut)
async def get_room(room_id: int, db: AsyncSession = Depends(get_db)):
    room = await db.get(LiveRoom, room_id)
    if room is None or room.del_flag != 0:
        raise HTTPException(status_code=404, detail="直播间不存在")
    return room


@router.put("/rooms/{room_id}", response_model=LiveRoomOut)
async def update_room(room_id: int, payload: LiveRoomUpdate, db: AsyncSession = Depends(get_db)):
    room = await get_room(room_id, db)
    data = payload.model_dump(exclude_unset=True)
    if "platform" in data and data["platform"] is not None:
        data["platform"] = normalize_platform(data["platform"])
    for key, value in data.items():
        setattr(room, key, value)
    await db.commit()
    await db.refresh(room)
    return room


@router.patch("/rooms/{room_id}/monitor", response_model=LiveRoomOut)
async def update_monitor(room_id: int, payload: MonitorUpdate, db: AsyncSession = Depends(get_db)):
    room = await get_room(room_id, db)
    room.monitor_enabled = payload.monitor_enabled
    await db.commit()
    await db.refresh(room)
    return room


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
    return await recorder.check_live_status()


@router.delete("/rooms/{room_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_room(room_id: int, db: AsyncSession = Depends(get_db)):
    room = await get_room(room_id, db)
    room.del_flag = 1
    await db.commit()


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
