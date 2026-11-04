"""集中处理录制日志、健康结果、统计查询及本地视频登记。"""

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.session import get_db_session
from app.models import LiveRoom, LiveRoomLog, LiveRoomLogVideo, LiveRoomStats


class RecordingRepository:
    """使用应用的会话工厂执行录制相关数据库操作。"""

    def __init__(self, app):
        self.app = app

    async def start_log(self, room_id, platform, owner, start_time):
        """在同一事务中创建录制日志并更新房间最近开播时间，返回日志 ID。"""
        async with get_db_session(self.app) as db:
            record = LiveRoomLog(
                live_room_id=room_id, platform=platform, owner=owner,
                start_live=start_time, create_time=func.current_timestamp(),
            )
            db.add(record)
            await db.execute(update(LiveRoom).where(LiveRoom.id == room_id).values(
                last_live_time=start_time, update_time=LiveRoom.update_time,
            ))
            await db.commit()
            return record.id

    async def finish_log(self, log_id, end_time, live_seconds, user_num, total_user, *, interrupted):
        """提交录制结束时间、人数和中断标记。"""
        async with get_db_session(self.app) as db:
            await db.execute(update(LiveRoomLog).where(LiveRoomLog.id == log_id).values(
                end_live=end_time, live_time=live_seconds, user_num=user_num,
                total_user=str(total_user) if total_user is not None else None, interrupted=interrupted,
            ))
            await db.commit()

    async def add_stats(self, room_id, log_id, online, likes, watched):
        """保存一次平台统计采样，人数使用文本保留平台的展示格式。"""
        async with get_db_session(self.app) as db:
            db.add(LiveRoomStats(
                live_room_id=room_id, live_room_log_id=log_id,
                online_count=str(online) if online is not None else None,
                like_count=str(likes) if likes is not None else None,
                watch_user_count=str(watched) if watched is not None else None,
                collect_time=func.current_timestamp(),
            ))
            await db.commit()

    async def recover_interrupted(self):
        """标记尚未结束的有效录制日志，返回本次更新数量。"""
        async with get_db_session(self.app) as db:
            result = await db.execute(update(LiveRoomLog).where(
                LiveRoomLog.end_live.is_(None), LiveRoomLog.interrupted.is_(False), LiveRoomLog.del_flag == 0,
            ).values(interrupted=True))
            await db.commit()
            return result.rowcount

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


class RecordingHistoryRepository:
    """复用请求会话查询录制历史、本地视频和统计数据。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_logs(self, room_id, limit):
        """按 ID 倒序查询有效日志，可按房间过滤。"""
        stmt = select(LiveRoomLog).where(LiveRoomLog.del_flag == 0)
        if room_id is not None:
            stmt = stmt.where(LiveRoomLog.live_room_id == room_id)
        return (await self.db.scalars(stmt.order_by(LiveRoomLog.id.desc()).limit(limit))).all()

    async def list_videos(self, log_id, limit):
        """按 ID 倒序查询有效视频，可按录制日志过滤。"""
        stmt = select(LiveRoomLogVideo).where(LiveRoomLogVideo.del_flag == 0)
        if log_id is not None:
            stmt = stmt.where(LiveRoomLogVideo.live_room_log_id == log_id)
        return (await self.db.scalars(stmt.order_by(LiveRoomLogVideo.id.desc()).limit(limit))).all()

    async def get_video(self, video_id):
        """按 ID 获取视频登记记录。"""
        return await self.db.get(LiveRoomLogVideo, video_id)

    async def list_stats(self, log_id, limit):
        """按 ID 倒序查询指定录制日志的统计采样。"""
        return (await self.db.scalars(select(LiveRoomStats).where(
            LiveRoomStats.live_room_log_id == log_id,
        ).order_by(LiveRoomStats.id.desc()).limit(limit))).all()
