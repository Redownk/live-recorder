"""将未正常结束的录制日志标记为中断，保留已有录制分片。"""


from app.core.logger import get_logger
from app.modules.recording.repository import RecordingRepository


logger = get_logger(__name__)


async def recover_interrupted_recordings(app):
    """标记未正常结束的录制日志，保留原始分片供后续处理。

    Args:
        app: 提供数据库会话工厂的应用实例。
    """
    count = await RecordingRepository(app).recover_interrupted()
    if count:
        logger.warning("发现 %s 条未正常结束的录制日志，已标记异常中断；原分片保留", count)
