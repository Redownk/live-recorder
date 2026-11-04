"""集中处理录制日志、健康结果、统计查询及本地视频登记。"""

from sqlalchemy import select, text

from app.core.session import get_db_session
from app.models import LiveRoomLogVideo


class RecordingRepository:
    """使用应用的会话工厂执行录制相关数据库操作。"""

    def __init__(self, app):
        self.app = app

    async def mark_interrupted(self, log_id):
        """将尚未写入结束时间的录制日志标记为中断。"""
        async with get_db_session(self.app) as db:
            await db.execute(text("UPDATE live_room_log SET interrupted=1 WHERE id=:id AND end_live IS NULL"), {"id": log_id})
            await db.commit()

    async def save_health_failure(self, log_id, room_id, restart_count, message, *, exhausted):
        """保存健康故障，并在恢复预算耗尽时暂停房间监控。

        Args:
            log_id: 录制日志 ID。
            room_id: 数据库直播间 ID。
            restart_count: 已执行的自动恢复次数。
            message: 健康故障说明。
            exhausted: 是否已用尽自动恢复次数。
        """
        async with get_db_session(self.app) as db:
            await db.execute(text("UPDATE live_room_log SET health_restart_count=:count, health_last_error=:error WHERE id=:id"),
                             {"count": restart_count, "error": message, "id": log_id})
            if exhausted:
                await db.execute(text("UPDATE live_room SET monitor_enabled=0 WHERE id=:id"), {"id": room_id})
            await db.commit()

    async def max_online_count(self, log_id):
        """返回指定录制日志的在线人数峰值，无统计时返回 None。"""
        async with get_db_session(self.app) as db:
            result = await db.execute(text("SELECT MAX(online_count) FROM live_room_stats WHERE live_room_log_id=:log_id"), {"log_id": log_id})
            return result.scalar()

    async def last_total_user_count(self, log_id):
        """返回指定录制日志最近一次采集的累计观看人数。"""
        async with get_db_session(self.app) as db:
            result = await db.execute(text("""
                SELECT watch_user_count FROM live_room_stats
                WHERE live_room_log_id=:log_id ORDER BY collect_time DESC, id DESC LIMIT 1
            """), {"log_id": log_id})
            return result.scalar()

    async def register_videos(self, room_id, log_id, videos, *, deduplicate=False):
        """在同一事务中登记视频文件元信息。

        Args:
            room_id: 数据库直播间 ID。
            log_id: 录制日志 ID。
            videos: 包含 file_name、file_path、file_size 和 duration 的字典列表。
            deduplicate: 是否跳过本次录制中已登记的文件路径。
        """
        async with get_db_session(self.app) as db:
            existing = set()
            if deduplicate:
                result = await db.execute(select(LiveRoomLogVideo.file_path).where(LiveRoomLogVideo.live_room_log_id == log_id))
                existing = set(result.scalars().all())
            db.add_all([
                LiveRoomLogVideo(live_room_id=room_id, live_room_log_id=log_id, **video)
                for video in videos if video["file_path"] not in existing
            ])
            await db.commit()
