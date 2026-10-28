import time
from datetime import datetime
import asyncio
from pathlib import Path

from app.core.session import get_db_session
from app.core.logger import get_logger
from app.core.log_context import recording_log_context
from app.services.platforms.recorder import get_ffmpeg_path
from app.models import LiveRoomLogVideo
from app.modules.settings.service import create_output_prefix
from app.modules.recording.status import get_recording_status
from app.modules.recording.tasks import get_recording_tasks
from app.modules.recording.health import RecordingHealthError, RecordingHealthSample, recording_file_size
from app.modules.recording.disk import DiskSpaceError
from sqlalchemy import text


logger = get_logger(__name__)

class BaseRecorder:

    def __init__(self, app, room):
        self.app = app
        self.room = room
        self.room_id = room["room_id"]
        self.platform = room["platform"]
        self._health_restart_count = 0
        self._health_last_error = None
        self._health_failed = False
        self._segment_health_error = None

    def health_options(self):
        from app.modules.settings.service import RecordingOptions

        manager = getattr(self.app.state, "recording_settings", None)
        return manager.settings if manager is not None else RecordingOptions()

    async def spawn_recording_process(self, command):
        command = [command[0], "-progress", "pipe:1", "-stats_period", "1", "-nostats", *command[1:]]
        return await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)

    async def wait_recording_process(self, process, output_file, log_id):
        self._segment_health_error = None
        stream = getattr(process, "stdout", None)
        sample = RecordingHealthSample(progress_expected=stream is not None)
        errors = bytearray()

        def publish():
            get_recording_status(self.app).health_updated(
                self.room["id"], log_id,
                sample.snapshot(self.health_options(), self._health_restart_count, self._health_last_error),
            )

        async def read_progress():
            if stream is not None:
                while line := await stream.readline():
                    sample.progress_line(line.decode("utf-8", errors="replace").strip())

        async def read_errors():
            stderr = getattr(process, "stderr", None)
            if stderr is not None:
                while chunk := await stderr.read(4096):
                    errors.extend(chunk)
                    del errors[:-4096]

        progress = asyncio.create_task(read_progress(), name="recording-progress")
        error_reader = asyncio.create_task(read_errors(), name="recording-errors")
        waiting = asyncio.create_task(process.wait(), name="recording-process-wait")
        publish()
        try:
            while True:
                done, _ = await asyncio.wait({waiting}, timeout=5)
                if done:
                    return await waiting
                sample.file_observation(await asyncio.to_thread(recording_file_size, output_file))
                if waiting.done():
                    return await waiting
                options = self.health_options()
                publish()
                if options.health_check_enabled:
                    failure = sample.failure(options)
                    if failure:
                        self._segment_health_error = failure
                        await self.stop_process(process)
                        return await waiting
        finally:
            # Reap the child before disposing its wait task, including manual/disk stops.
            await self.stop_process(process)
            if not error_reader.done() and getattr(process, "returncode", None) is not None:
                try:
                    await asyncio.wait_for(asyncio.shield(error_reader), timeout=1)
                except (TimeoutError, OSError):
                    pass
            for task in (waiting, progress, error_reader):
                if not task.done():
                    task.cancel()
            await asyncio.gather(waiting, progress, error_reader, return_exceptions=True)
            if (not asyncio.current_task().cancelling() and getattr(process, "returncode", 0)
                    and self._segment_health_error is None):
                logger.warning(self._log_message("FFmpeg 异常退出: %s"), errors.decode("utf-8", errors="replace") or "无错误输出",
                               extra={"event_code": "ffmpeg_exit"})

    async def complete_recording_segment(self, output_file, log_id):
        path = Path(output_file)
        size = recording_file_size(path)
        unhealthy = self._segment_health_error is not None
        if unhealthy:
            # Even a short nonempty failed segment is retained; the next attempt gets a new name.
            await self.health_failure(log_id, self._segment_health_error)
            return 1
        if size > 1024:
            return 1
        if path.exists():
            path.unlink()
        return 0

    async def health_failure(self, log_id, message):
        options = self.health_options()
        self._health_last_error = message
        exhausted = self._health_restart_count >= options.health_max_restarts
        if exhausted:
            self._health_failed = True
            get_recording_tasks(self.app).disabled_keys.add((self.platform, str(self.room_id)))
        else:
            self._health_restart_count += 1
        logger.warning(self._log_message("健康检测异常: %s; 自动恢复 %s/%s; %s"), message,
                       self._health_restart_count, options.health_max_restarts, "暂停监控" if exhausted else "重新获取直播流",
                       extra={"event_code": "recording_health"})
        try:
            async with get_db_session(self.app) as db:
                await db.execute(text("UPDATE live_room_log SET health_restart_count=:count, health_last_error=:error WHERE id=:id"),
                                 {"count": self._health_restart_count, "error": message, "id": log_id})
                if exhausted:
                    await db.execute(text("UPDATE live_room SET monitor_enabled=0 WHERE id=:id"), {"id": self.room["id"]})
                await db.commit()
        except Exception:
            logger.exception(self._log_message("健康检测结果写入失败"))
        tracker = get_recording_status(self.app)
        session = tracker.sessions.get(self.room["id"])
        if session is not None and session.log_id == log_id:
            tracker.health_updated(self.room["id"], log_id, {**(session.health or {}), "state": "recovering",
                "restart_count": self._health_restart_count, "last_error": message})
        if exhausted:
            raise RecordingHealthError(f"健康检测自动恢复次数已用尽，已暂停该房间监控：{message}")

    async def recover_recording_stream(self, previous_url):
        from app.modules.recording.disk import get_disk_guard

        prefix = getattr(self, "_output_prefix", None)
        if prefix is not None:
            try:
                await get_disk_guard(self.app).ensure_can_start(prefix.parent)
            except DiskSpaceError:
                self._health_failed = True
                raise
        info = await asyncio.wait_for(self.check_live_status(), timeout=30)
        if not info.get("is_live"):
            return None
        await asyncio.sleep(min(5 * self._health_restart_count, 30))
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
            from app.modules.recording.disk import DiskSpaceError, get_disk_guard
            from app.modules.settings.service import resolve_save_path

            guard = get_disk_guard(self.app)
            directory = resolve_save_path(self.app.state.recording_settings.settings.save_path)
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
                async with get_db_session(self.app) as db:
                    await db.execute(text("UPDATE live_room_log SET interrupted=1 WHERE id=:id AND end_live IS NULL"), {"id": log_id})
                    await db.commit()
        finally:
            prefix = getattr(self, "_output_prefix", None)
            if prefix is not None:
                get_recording_tasks(self.app).output_prefixes.discard(prefix)
                get_recording_tasks(self.app).output_paths.pop((self.platform, str(self.room_id)), None)

    async def stop_process(self, process):
        if process is None or process.returncode is not None:
            return
        try:
            process.terminate()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except asyncio.TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()

    async def check_live_status(self):
        raise NotImplementedError

    async def record(self, live_info):
        raise NotImplementedError

    async def create_output_prefix(self, live_info, start_time):
        prefix = await create_output_prefix(self.app, self.room, live_info, start_time)
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
        async with get_db_session(self.app) as db:
            result = await db.execute(text("""
                SELECT MAX(online_count)
                FROM live_room_stats
                WHERE live_room_log_id = :log_id
            """), {
                "log_id": log_id
            })
            return result.scalar()

    async def _get_last_total_user_count(self, log_id):
        async with get_db_session(self.app) as db:
            result = await db.execute(text("""
                SELECT watch_user_count
                FROM live_room_stats
                WHERE live_room_log_id = :log_id
                ORDER BY collect_time DESC, id DESC
                LIMIT 1
            """), {
                "log_id": log_id
            })
            return result.scalar()

    @recording_log_context
    async def _post_process(self, file_name, segment_count, log_id):

        import os

        logger.info(self._log_message("开始后处理"))
        get_recording_tasks(self.app).phases[(self.platform, str(self.room_id))] = "merging"

        if segment_count <= 0:
            logger.info(self._log_message("没有分段文件，跳过处理"))
            return

        formats = {}
        for extension in ("ts", "flv"):
            segments = [Path(f"{file_name}_{i}.{extension}") for i in range(1, segment_count + 1)]
            segments = [path for path in segments if path.is_file() and path.stat().st_size > 0]
            if segments:
                formats[extension] = segments
        if len(formats) > 1:
            logger.warning(self._log_message("录制流格式发生变化，保留全部 TS / FLV 分片，不自动合并"))
            return
        if not formats:
            logger.info(self._log_message("没有有效分段文件，跳过处理"))
            return
        ext, segments = next(iter(formats.items()))

        from app.modules.recording.disk import DiskSpaceError, get_disk_guard

        try:
            await get_disk_guard(self.app).ensure_can_start(segments[0].parent, sum(path.stat().st_size for path in segments))
        except DiskSpaceError as exc:
            logger.warning(self._log_message("%s"), exc)
            return

        ffmpeg_path = get_ffmpeg_path()
        list_file = f"{file_name}_filelist.txt"

        with open(list_file, "w", encoding="utf-8") as f:
            for segment in segments:
                escaped_path = segment.resolve().as_posix().replace("'", "'\\''")
                f.write(f"file '{escaped_path}'\n")

        merged_file = f"{file_name}.{ext}"

        logger.info(self._log_message("开始合并分段"))

        merge_cmd = [
            ffmpeg_path,
            "-nostdin", "-n",
            "-f", "concat",
            "-safe", "0",
            "-i", list_file,
            "-c", "copy",
            merged_file
        ]

        process = await asyncio.create_subprocess_exec(
            *merge_cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        try:
            return_code = await process.wait()
        finally:
            await self.stop_process(process)

        if return_code != 0 or not os.path.isfile(merged_file) or os.path.getsize(merged_file) == 0:
            logger.warning(self._log_message("合并失败，保留分段文件，退出码: %s"), return_code, extra={"event_code": "processing"})
            return

        logger.info(self._log_message("分段合并完成"))

        # Register the local video before cleaning up recording segments.
        try:

            # 获取文件大小 (byte)
            file_size = os.path.getsize(merged_file)

            # 使用 ffprobe 获取时长 (秒)
            duration = 0
            probe_cmd = [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", merged_file
            ]

            try:
                probe_process = await asyncio.create_subprocess_exec(
                    *probe_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                try:
                    stdout, stderr = await probe_process.communicate()
                finally:
                    await self.stop_process(probe_process)
                if probe_process.returncode == 0:
                    duration_str = stdout.decode('utf-8').strip()
                    if duration_str:
                        duration = int(float(duration_str))
                else:
                    logger.warning("ffprobe 错误: %s", stderr.decode("utf-8", errors="replace"))
            except (OSError, ValueError) as exc:
                logger.warning(self._log_message("视频时长读取失败: %s"), exc)

            async with get_db_session(self.app) as db:
                db.add(LiveRoomLogVideo(
                    live_room_id=self.room["id"],
                    live_room_log_id=log_id,
                    file_name=os.path.basename(merged_file),
                    file_path=str(Path(merged_file).resolve()),
                    file_size=file_size,
                    duration=duration,
                ))
                await db.commit()
            logger.info(self._log_message("本地视频已保存: %s"), merged_file)

        except Exception as e:
            logger.exception(self._log_message("本地视频登记失败，保留录制文件: %s"), e)
            return

        logger.info(self._log_message("开始清理临时文件"))
        try:
            os.remove(list_file)
            for segment in segments:
                segment.unlink()

            logger.info(self._log_message("临时文件清理完成"))

        except Exception as e:
            logger.exception(self._log_message("清理文件失败: %s"), e)

        logger.info(self._log_message("后处理完成"))
