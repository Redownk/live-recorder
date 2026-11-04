"""集中读写全局录制设置和房间覆盖设置。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RecordingSettings, RoomRecordingSettings


class SettingsRepository:
    """使用当前会话保存设置；仅在提交成功后由业务层更新内存配置。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_global(self):
        """返回全局录制设置，尚未保存时返回 None。"""
        return await self.db.get(RecordingSettings, 1)

    async def list_overrides(self):
        """读取所有房间覆盖设置，供启动时恢复内存配置。"""
        return (await self.db.scalars(select(RoomRecordingSettings))).all()

    async def customized_room_ids(self):
        """返回已保存独立录制设置的房间 ID 集合。"""
        return set((await self.db.scalars(select(RoomRecordingSettings.room_id))).all())

    async def has_overrides(self, room_id):
        """判断房间是否存在独立录制设置。"""
        return await self.db.get(RoomRecordingSettings, room_id) is not None

    async def save_global(self, values):
        """创建或更新全局设置，并提交完整配置。"""
        record = await self.get_global()
        if record is None:
            record = RecordingSettings(id=1)
            self.db.add(record)
        for name, value in values.items():
            setattr(record, name, value)
        await self.db.commit()

    async def save_overrides(self, room_id, values):
        """完整替换房间覆盖设置；空字典表示恢复继承全局配置。"""
        record = await self.db.get(RoomRecordingSettings, room_id)
        if not values:
            if record is not None:
                await self.db.delete(record)
        else:
            if record is None:
                record = RoomRecordingSettings(room_id=room_id)
                self.db.add(record)
            for name, value in values.items():
                setattr(record, name, value)
        await self.db.commit()
