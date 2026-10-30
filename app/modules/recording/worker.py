
import asyncio
from time import monotonic
from sqlalchemy import text
from app.services.platforms.recorder_factory import create_recorder
from app.core.logger import setup_logging, get_logger
from app.core.log_context import room_log_fields
from app.modules.recording.disk import DiskSpaceError

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
    last_checks = {}
    while not stop_event.is_set():
        settings_manager.changed.clear()
        interval = settings_manager.settings.check_interval_seconds
        try:
            async with app.state.db() as db:
                result = await db.execute(text("select * from live_room where monitor_enabled=1 and del_flag=0"))
                rooms = result.mappings().all()
            enabled_ids = {room["id"] for room in rooms}
            last_checks = {key: value for key, value in last_checks.items() if key in enabled_ids}
            logger.info("本轮扫描启用直播间数量: %s", len(rooms))
            for room in rooms:
                if stop_event.is_set():
                    break
                options = settings_manager.for_room(room)
                revision = (settings_manager.schedule_revision, settings_manager.room_revisions.get(room["id"], 0), options.check_interval_seconds)
                previous = last_checks.get(room["id"])
                if previous and previous[1] == revision and monotonic() < previous[0] + options.check_interval_seconds:
                    continue
                try:
                    logger.info(
                        "开始检查直播间 platform=%s room_id=%s owner=%s",
                        room.get("platform"),
                        room.get("room_id"),
                        room.get("owner"),
                        extra=room_log_fields(room),
                    )
                    recorder = create_recorder(app, room)
                    if recorder:
                        await recorder.start()
                    else:
                        logger.warning(
                            "未找到平台录制器 platform=%s room_id=%s",
                            room.get("platform"),
                            room.get("room_id"),
                            extra=room_log_fields(room),
                        )
                except DiskSpaceError as exc:
                    logger.warning("磁盘保护跳过录制 platform=%s room_id=%s: %s", room.get("platform"), room.get("room_id"), exc,
                                   extra={**room_log_fields(room), "event_code": "disk_space"})
                except Exception:
                    logger.exception(
                        "爬虫异常 platform=%s room_id=%s",
                        room.get("platform"),
                        room.get("room_id"),
                        extra={**room_log_fields(room), "event_code": "live_check"},
                    )
                finally:
                    last_checks[room["id"]] = (monotonic(), revision)
            deadlines = [last_checks[room["id"]][0] + settings_manager.for_room(room).check_interval_seconds
                         for room in rooms if room["id"] in last_checks]
            if deadlines:
                interval = max(0.05, min(deadlines) - monotonic())
        except Exception:
            logger.exception("爬虫批次异常")
        await wait_for_next_check(stop_event, settings_manager.changed, interval)
    logger.info("爬虫协程停止")
