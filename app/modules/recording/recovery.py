"""将未正常结束的录制日志标记为中断，保留已有录制分片。"""


from sqlalchemy import update

from app.core.logger import get_logger
from app.core.session import get_db_session
from app.models import LiveRoomLog


logger = get_logger(__name__)


async def recover_interrupted_recordings(app):
    """标记未正常结束的录制日志，保留原始分片供后续处理。

    Args:
        app: 提供数据库会话工厂的应用实例。
    """
    async with get_db_session(app) as db:
        result = await db.execute(
            update(LiveRoomLog)
            .where(LiveRoomLog.end_live.is_(None), LiveRoomLog.interrupted.is_(False), LiveRoomLog.del_flag == 0)
            .values(interrupted=True)
        )
        await db.commit()
    if result.rowcount:
        logger.warning("发现 %s 条未正常结束的录制日志，已标记异常中断；原分片保留", result.rowcount)
