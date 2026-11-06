"""按各直播间的检查间隔轮询开播状态，并响应设置变更和停止信号。"""


import asyncio
from time import monotonic
from app.core.session import get_db_session
from app.modules.live_rooms.repository import LiveRoomRepository
from app.modules.recording.factory import create_recorder
from app.core.logger import setup_logging, get_logger
from app.core.log_context import room_log_fields
from app.modules.recording.log_events import room_label

setup_logging()
logger = get_logger(__name__)


async def wait_for_next_check(stop_event, settings_changed, interval):
    """等待下次检查时间，允许停止或设置变更信号提前唤醒。

    Args:
        stop_event: 轮询停止事件。
        settings_changed: 录制设置变更事件。
        interval: 最长等待时间，单位为秒。
    """
    tasks = [asyncio.create_task(stop_event.wait()), asyncio.create_task(settings_changed.wait())]
    try:
        await asyncio.wait(tasks, timeout=interval, return_when=asyncio.FIRST_COMPLETED)
    finally:
        # 超时或任一信号触发后，回收两个等待任务，避免每轮遗留协程。
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def crawler_loop(app, stop_event):
    """按直播间各自的检查间隔轮询并尝试启动录制。

    Args:
        app: 提供数据库和录制设置管理器的应用实例。
        stop_event: 停止事件，触发后结束轮询。
    """
    logger.info("直播间自动检测已启动")
    settings_manager = app.state.recording_settings
    last_checks = {}
    previous_enabled = None
    while not stop_event.is_set():
        settings_manager.changed.clear()
        interval = settings_manager.settings.check_interval_seconds
        try:
            async with get_db_session(app) as db:
                rooms = await LiveRoomRepository(db).monitored_snapshots()
            enabled_ids = {room["id"] for room in rooms}
            last_checks = {key: value for key, value in last_checks.items() if key in enabled_ids}
            if enabled_ids != previous_enabled:
                logger.info("监控列表已更新：启用 %s 个直播间，各房间按自身检查间隔检测", len(rooms))
                previous_enabled = enabled_ids
            logger.debug("本轮扫描启用直播间数量：%s", len(rooms))
            for room in rooms:
                if stop_event.is_set():
                    break
                options = settings_manager.for_room(room)
                # 设置版本变化时跳过旧检查间隔的限制，使新调度配置及时生效。
                revision = (settings_manager.schedule_revision, settings_manager.room_revisions.get(room["id"], 0), options.check_interval_seconds)
                previous = last_checks.get(room["id"])
                if previous and previous[1] == revision and monotonic() < previous[0] + options.check_interval_seconds:
                    continue
                recorder = None
                try:
                    recorder = create_recorder(app, room)
                    if recorder:
                        await recorder.start()
                    else:
                        logger.warning(
                            "%s 无法检测：未找到对应的平台录制器",
                            room_label(room),
                            extra=room_log_fields(room),
                        )
                except Exception:
                    if recorder is None:
                        logger.exception("%s 创建录制器失败", room_label(room), extra={**room_log_fields(room), "event_code": "live_check"})
                    elif getattr(recorder, "_check_failure_handled", False):
                        # 具体失败原因由录制器记录，此处仅保持轮询继续，避免重复堆栈。
                        logger.debug("%s 本轮检测失败，等待下次检测", room_label(room), extra=room_log_fields(room))
                    else:
                        logger.exception("%s 处理检测任务失败", room_label(room), extra={**room_log_fields(room), "event_code": "live_check"})
                finally:
                    last_checks[room["id"]] = (monotonic(), revision)
            deadlines = [last_checks[room["id"]][0] + settings_manager.for_room(room).check_interval_seconds
                         for room in rooms if room["id"] in last_checks]
            if deadlines:
                interval = max(0.05, min(deadlines) - monotonic())
        except Exception:
            logger.exception("直播间检测批次失败，将在下次调度时重试", extra={"event_code": "live_check"})
        await wait_for_next_check(stop_event, settings_manager.changed, interval)
    logger.info("直播间自动检测已停止")
