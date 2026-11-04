"""协调录制任务、平台适配、健康恢复及输出处理。"""

import asyncio
from pathlib import Path

from app.core.logger import get_logger
from app.core.log_context import recording_log_context
from app.modules.settings.service import create_output_prefix
from app.modules.recording.status import get_recording_status
from app.modules.recording.tasks import get_recording_tasks
from app.modules.recording.health import RecordingHealthError, RecordingRecoveryState, recording_file_size
from app.modules.recording.disk import DiskSpaceError
from app.modules.recording.outputs import RecordingOutput
from app.modules.recording.process import RecordingProcessMonitor, spawn_recording_process
from app.modules.recording.repository import RecordingRepository
from app.shared.media.process import stop_process


logger = get_logger(__name__)


class BaseRecorder:
    """协调平台录制流程，将进程、媒体文件及数据库操作委托给独立组件。"""

    def __init__(self, app, room):
        self.app = app
        self.room = room
        self.room_id = room["room_id"]
        self.platform = room["platform"]
        self._recovery = RecordingRecoveryState()
        self.repository = RecordingRepository(app)
        self.output = RecordingOutput(app, room, self.repository)
        self._segment_health_error = None
        self._recording_options = None
        self._timed_output = None
        self._segment_had_data = False

    def recording_options(self):
        """获取并缓存本轮录制使用的房间配置，无管理器时使用默认配置。"""
        # 每个录制器首次读取后缓存选项，供本轮录制各阶段复用。
        if self._recording_options is None:
            manager = getattr(self.app.state, "recording_settings", None)
            self._recording_options = manager.for_room(self.room) if manager is not None else self.health_options()
        return self._recording_options

    def health_options(self):
        from app.modules.settings.service import RecordingOptions

        manager = getattr(self.app.state, "recording_settings", None)
        return manager.settings if manager is not None else RecordingOptions()

    async def spawn_recording_process(self, command):
        """按本轮录制配置启动进程，并保存定时分片跟踪器。"""
        process, self._timed_output = await spawn_recording_process(command, self.recording_options().segment_minutes)
        return process

    async def wait_recording_process(self, process, output_file, log_id):
        """委托进程监控器采样，将健康状态发布到当前录制会话。"""
        self._segment_health_error = None

        def publish(sample):
            get_recording_status(self.app).health_updated(
                self.room["id"], log_id,
                sample.snapshot(self.health_options(), self._recovery.restart_count, self._recovery.last_error),
            )

        monitor = RecordingProcessMonitor(options=self.health_options, on_sample=publish, timed_output=self._timed_output)
        try:
            return await monitor.wait(process, output_file)
        finally:
            self._segment_health_error = monitor.health_error

    async def complete_recording_segment(self, output_file, log_id):
        if self._timed_output is not None:
            size, index = await asyncio.to_thread(self._timed_output.observation)
            self._segment_had_data = size > 1024
            if self._segment_health_error is not None:
                await self.health_failure(log_id, self._segment_health_error)
            return max(1, index - self._timed_output.first_index + 1)
        path = Path(output_file)
        size = recording_file_size(path)
        self._segment_had_data = size > 1024
        unhealthy = self._segment_health_error is not None
        if unhealthy:
            # 健康失败的分片保留原文件，下次尝试使用新编号。
            await self.health_failure(log_id, self._segment_health_error)
            return 1
        if size > 1024:
            return 1
        if path.exists():
            path.unlink()
        return 0

    async def health_failure(self, log_id, message):
        options = self.health_options()
        exhausted = self._recovery.register_failure(message, options.health_max_restarts)
        if exhausted:
            get_recording_tasks(self.app).disabled_keys.add((self.platform, str(self.room_id)))
        logger.warning(self._log_message("健康检测异常: %s; 自动恢复 %s/%s; %s"), message,
                       self._recovery.restart_count, options.health_max_restarts, "暂停监控" if exhausted else "重新获取直播流",
                       extra={"event_code": "recording_health"})
        try:
            await self.repository.save_health_failure(
                log_id, self.room["id"], self._recovery.restart_count, message, exhausted=exhausted,
            )
        except Exception:
            logger.exception(self._log_message("健康检测结果写入失败"))
        tracker = get_recording_status(self.app)
        session = tracker.sessions.get(self.room["id"])
        if session is not None and session.log_id == log_id:
            tracker.health_updated(self.room["id"], log_id, {**(session.health or {}), "state": "recovering",
                "restart_count": self._recovery.restart_count, "last_error": message})
        if exhausted:
            raise RecordingHealthError(f"健康检测自动恢复次数已用尽，已暂停该房间监控：{message}")

    async def recover_recording_stream(self, previous_url):
        from app.modules.recording.disk import get_disk_guard

        prefix = getattr(self, "_output_prefix", None)
        if prefix is not None:
            try:
                await get_disk_guard(self.app).ensure_can_start(prefix.parent)
            except DiskSpaceError:
                self._recovery.failed = True
                raise
        info = await asyncio.wait_for(self.check_live_status(), timeout=30)
        if not info.get("is_live"):
            return None
        await asyncio.sleep(min(5 * self._recovery.restart_count, 30))
        stream_url = await asyncio.wait_for(self.refresh_stream_url(info, previous_url), timeout=30)
        if not isinstance(stream_url, str) or not stream_url.strip():
            raise ValueError("重新获取直播流失败")
        return stream_url

    async def refresh_stream_url(self, live_info, previous_url):
        return previous_url

    def _log_message(self, message: str) -> str:
        return f"[platform={self.platform} room_id={self.room_id}] {message}"

    @recording_log_context
    async def start(self, manual=False, token=None):
        manager = get_recording_tasks(self.app)
        key = (self.platform, str(self.room_id))
        if self.room.get("id") is not None:
            manager.room_ids[key] = self.room["id"]
        token = token if token is not None else manager.begin_check(key, manual=manual)
        if token is None:
            logger.info(self._log_message("已有检查或录制任务，跳过"))
            return {"status": "busy"}
        if manager.checks.get(key) is not token:
            return {"status": "stopped"}
        logger.info(self._log_message("开始检测直播状态"))
        try:
            self._recording_options = None
            from app.modules.recording.disk import DiskSpaceError, get_disk_guard
            from app.modules.settings.service import resolve_save_path

            guard = get_disk_guard(self.app)
            directory = resolve_save_path(self.recording_options().save_path)
            await guard.ensure_can_start(directory)
            if manager.checks.get(key) is not token:
                return {"status": "stopped"}
            check = asyncio.create_task(self.check_live_status())
            manager.check_tasks[key] = check
            try:
                live_info = await asyncio.wait_for(check, timeout=30)
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling():
                    raise
                return {"status": "stopped"}
            if not live_info["is_live"]:
                logger.info(self._log_message("未开播，跳过录制: %s"), live_info)
                manager.notices.pop(key, None)
                return {"status": "offline"}
            await guard.ensure_can_start(directory)
            logger.info(self._log_message("检测到开播，准备录制: %s"), live_info.get("title") or live_info.get("owner"))
            started = manager.start_recording(key, lambda: self.record(live_info), self.finish_recording_task,
                                              token=token, manual=manual)
            return {"status": "started" if started else "stopped"}
        except DiskSpaceError as exc:
            manager.notices[key] = {"state": "disk_blocked", "message": str(exc)}
            raise
        except Exception:
            logger.exception(self._log_message("直播状态检查失败"), extra={"event_code": "live_check"})
            raise
        finally:
            manager.end_check(key, token)

    @recording_log_context
    async def finish_recording_task(self):
        try:
            log_id = getattr(self, "_log_id", None)
            if log_id is not None:
                self.recording_finished(log_id)
                await self.repository.mark_interrupted(log_id)
        finally:
            prefix = getattr(self, "_output_prefix", None)
            if prefix is not None:
                get_recording_tasks(self.app).output_prefixes.discard(prefix)
                get_recording_tasks(self.app).output_paths.pop((self.platform, str(self.room_id)), None)

    async def stop_process(self, process):
        """委托公共进程工具终止并回收录制子进程。"""
        await stop_process(process)

    async def check_live_status(self):
        raise NotImplementedError

    async def record(self, live_info):
        raise NotImplementedError

    async def create_output_prefix(self, live_info, start_time):
        prefix = await create_output_prefix(self.app, self.room, live_info, start_time, settings=self.recording_options())
        self._output_prefix = Path(prefix).resolve()
        get_recording_tasks(self.app).output_prefixes.add(self._output_prefix)
        get_recording_tasks(self.app).output_paths[(self.platform, str(self.room_id))] = self._output_prefix
        return prefix

    def recording_started(self, log_id):
        get_recording_status(self.app).started(self.room["id"], log_id)

    def recording_reconnecting(self, log_id):
        get_recording_status(self.app).reconnecting(self.room["id"], log_id)

    def recording_finished(self, log_id):
        get_recording_status(self.app).finished(self.room["id"], log_id)
        get_recording_tasks(self.app).phases[(self.platform, str(self.room_id))] = "finishing"

    async def _get_max_online_count(self, log_id):
        return await self.repository.max_online_count(log_id)

    async def _get_last_total_user_count(self, log_id):
        return await self.repository.last_total_user_count(log_id)

    @recording_log_context
    async def _post_process(self, file_name, segment_count, log_id):
        """委托输出处理器合并或登记录制分片。"""
        await self.output.finalize(
            file_name, segment_count, log_id,
            segment_minutes=self.recording_options().segment_minutes, timed_output=self._timed_output,
        )

    @recording_log_context
    async def register_timed_segments(self, file_name, segment_count, log_id, probe_durations=True):
        """委托输出处理器登记分片，中断时允许跳过媒体探测。"""
        await self.output.register_segments(
            file_name, segment_count, log_id, timed_output=self._timed_output, probe_durations=probe_durations,
        )
