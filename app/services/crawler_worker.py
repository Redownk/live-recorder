
import asyncio
from sqlalchemy import text
from app.services.platforms.recorder_factory import create_recorder
from app.core.logger import setup_logging, get_logger

setup_logging()
logger = get_logger(__name__)

async def crawler_loop(app, stop_event):
    logger.info("爬虫协程启动")
    while not stop_event.is_set():
        try:
            async with app.state.db() as db:
                result = await db.execute(text("select * from live_room where monitor_enabled=1 and del_flag=0"))
                rooms = result.mappings().all()
            logger.info("本轮扫描启用直播间数量: %s", len(rooms))
            for room in rooms:
                try:
                    logger.info(
                        "开始检查直播间 platform=%s room_id=%s owner=%s",
                        room.get("platform"),
                        room.get("room_id"),
                        room.get("owner"),
                    )
                    recorder = create_recorder(app, room)
                    if recorder:
                        await recorder.start()
                    else:
                        logger.warning(
                            "未找到平台录制器 platform=%s room_id=%s",
                            room.get("platform"),
                            room.get("room_id"),
                        )
                except Exception:
                    logger.exception(
                        "爬虫异常 platform=%s room_id=%s",
                        room.get("platform"),
                        room.get("room_id"),
                    )
            await asyncio.sleep(5)
        except Exception:
            logger.exception("爬虫批次异常")
            await asyncio.sleep(5)
    logger.info("爬虫协程停止")
