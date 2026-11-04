"""集中处理直播间查询、保存和轮询所需的数据快照。"""

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LiveRoom


class LiveRoomRepository:
    """复用调用方的会话；每次写入完整提交，提交失败由会话提供方回滚。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_active(self, keyword=None, *, ascending=False):
        """查询未删除的直播间，支持关键词过滤和导出所需的正序排列。"""
        stmt = select(LiveRoom).where(LiveRoom.del_flag == 0)
        if keyword:
            pattern = f"%{keyword}%"
            stmt = stmt.where(or_(*(field.like(pattern) for field in (
                LiveRoom.room_id, LiveRoom.owner, LiveRoom.remark, LiveRoom.platform,
            ))))
        stmt = stmt.order_by(LiveRoom.id.asc() if ascending else LiveRoom.id.desc())
        return (await self.db.scalars(stmt)).all()

    async def get_active(self, room_id):
        """按数据库 ID 获取未删除的房间，不存在时返回 None。"""
        room = await self.db.get(LiveRoom, room_id)
        return room if room is not None and room.del_flag == 0 else None

    async def active_identities(self):
        """查询已有平台与房间号，用于批量导入去重。"""
        return (await self.db.execute(select(LiveRoom.platform, LiveRoom.room_id).where(LiveRoom.del_flag == 0))).all()

    async def monitored_snapshots(self):
        """返回启用监控的房间字典，允许会话关闭后交给后台任务使用。"""
        rooms = (await self.db.scalars(select(LiveRoom).where(
            LiveRoom.monitor_enabled.is_(True), LiveRoom.del_flag == 0,
        ))).all()
        return [{column.name: getattr(room, column.name) for column in LiveRoom.__table__.columns} for room in rooms]

    async def save(self, room, *, refresh=False):
        """提交新增或已修改的房间，按需刷新数据库生成的字段。"""
        self.db.add(room)
        await self.db.commit()
        if refresh:
            await self.db.refresh(room)
        return room

    async def add_many(self, rooms):
        """在同一事务中提交全部导入记录。"""
        self.db.add_all(rooms)
        await self.db.commit()

    async def refresh(self, room):
        """在获取录制控制锁后重新读取房间，避免使用过期状态。"""
        await self.db.refresh(room)
