
import asyncio
from sqlalchemy import text
from app.services.platforms.recorder_factory import create_recorder
from app.core.logger import setup_logging, get_logger

setup_logging()
logger = get_logger(__name__)


async def wait_for_next_check(stop_event, settings_changed, interval):
    tasks = [asyncio.create_task(stop_event.wait()), asyncio.create_task(settings_changed.wait())]
    try:
        await asyncio.wait(tasks, timeout=interval, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def crawler_loop(app, stop_event):
    logger.info("爬虫协程启动")
    settings_manager = app.state.recording_settings
    while not stop_event.is_set():
        settings_manager.changed.clear()
        interval = settings_manager.settings.check_interval_seconds
        try:
            async with app.state.db() as db:
                result = await db.execute(text("select * from live_room where monitor_enabled=1 and del_flag=0"))
                rooms = result.mappings().all()
            logger.info("本轮扫描启用直播间数量: %s", len(rooms))
            for room in rooms:
                if stop_event.is_set():
                    break
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
        except Exception:
            logger.exception("爬虫批次异常")
        await wait_for_next_check(stop_event, settings_manager.changed, interval)
    logger.info("爬虫协程停止")
