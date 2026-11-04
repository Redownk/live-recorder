"""导出直播间备份，校验导入条目并按平台和房间号去重。"""

from datetime import datetime, timezone

from pydantic import ValidationError
from sqlalchemy import select

from app.models import LiveRoom
from app.modules.live_rooms.schemas import RoomBackupEntry


BACKUP_FIELDS = tuple(RoomBackupEntry.model_fields)


async def export_rooms(db):
    """返回未删除直播间的可迁移信息，排除运行状态和数据库内部字段。"""
    rooms = (await db.execute(select(LiveRoom).where(LiveRoom.del_flag == 0).order_by(LiveRoom.id))).scalars().all()
    return {
        "format": "live-recorder-rooms", "version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "rooms": [{field: getattr(room, field) for field in BACKUP_FIELDS} for room in rooms],
    }


async def plan_import(document, db):
    """逐行校验备份并标记新增、重复和无效记录，不修改数据库。

    Args:
        document: 已校验格式版本的备份文档。
        db: 当前异步数据库会话。

    Returns:
        逐行结果及与新增结果对应的备份条目列表。
    """
    existing = (await db.execute(select(LiveRoom.platform, LiveRoom.room_id).where(LiveRoom.del_flag == 0))).all()
    seen = {(platform.strip().upper(), room_id.strip()) for platform, room_id in existing}
    rows, entries = [], []
    for index, raw in enumerate(document.rooms, start=1):
        source_row = document.source_rows[index - 1] if document.source_rows is not None else index
        if isinstance(raw, dict) and raw.get("__import_error__"):
            rows.append({"row": source_row, "status": "invalid", "message": raw["__import_error__"]})
            continue
        try:
            entry = RoomBackupEntry.model_validate(raw)
        except ValidationError as exc:
            errors = exc.errors(include_input=False, include_url=False)
            message = "；".join(f"{'.'.join(map(str, error['loc'])) or '条目'}: {error['msg']}" for error in errors[:5])
            rows.append({"row": source_row, "status": "invalid", "message": message[:1000]})
            continue
        key = (entry.platform, entry.room_id)
        row = {"row": source_row, "platform": entry.platform, "room_id": entry.room_id,
               "owner": entry.owner, "status": "new", "message": "可导入"}
        if key in seen:
            row.update(status="duplicate", message="已有相同平台和房间号，或文件内重复，已跳过")
        else:
            seen.add(key)
            entries.append(entry)
        rows.append(row)
    return rows, entries


def import_summary(rows):
    """汇总逐行处理结果。"""
    return {"total": len(rows), **{state: sum(row["status"] == state for row in rows)
                                  for state in ("new", "imported", "duplicate", "invalid")}, "rows": rows}


async def import_rooms(payload, db):
    """重新校验重复项，并在同一事务中写入所有有效新增直播间。"""
    rows, entries = await plan_import(payload.document, db)
    rooms = []
    for entry in entries:
        fields = entry.model_dump()
        fields["monitor_enabled"] = payload.enable_monitoring and entry.monitor_enabled
        rooms.append(LiveRoom(**fields))
    db.add_all(rooms)
    await db.commit()
    for row in rows:
        if row["status"] == "new":
            row.update(status="imported", message="已导入")
    return import_summary(rows)
