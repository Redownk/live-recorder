"""协调录制分片合并、媒体信息探测、视频登记及成功后的文件清理。"""

import asyncio
from pathlib import Path

from app.core.logger import get_logger
from app.core.log_context import current_log_context
from app.modules.recording.disk import DiskSpaceError, get_disk_guard
from app.modules.recording.tasks import get_recording_tasks
from app.modules.recording.log_events import room_label
from app.shared.media.concat import merge_segments
from app.shared.media.probe import probe_duration


logger = get_logger(__name__)


class RecordingOutput:
    """处理录制输出，只有成功登记视频后才清理原分片。"""

    def __init__(self, app, room, repository):
        self.app = app
        self.room = room
        self.repository = repository

    def _log_message(self, message):
        """为文件处理日志补充与录制流程一致的房间和录制编号。"""
        log_id = current_log_context().get("recording_log_id")
        return f"{room_label(self.room)}{f' [录制 #{log_id}]' if log_id is not None else ''} {message}"

    async def finalize(self, file_name, segment_count, log_id, *, segment_minutes=0, timed_output=None):
        """按录制设置合并分片或逐个登记定时分片。

        Args:
            file_name: 录制文件路径前缀。
            segment_count: 本轮可能存在的最大分片编号。
            log_id: 录制日志 ID。
            segment_minutes: 定时分片时长；为 0 时执行合并。
            timed_output: 当前定时分片跟踪器，允许为 None。
        """
        logger.debug(self._log_message("开始整理录制文件"))
        key = (self.room["platform"], str(self.room["room_id"]))
        get_recording_tasks(self.app).phases[key] = "registering" if segment_minutes else "merging"
        if segment_count <= 0:
            logger.warning(self._log_message("没有录制分片，未生成视频文件"), extra={"event_code": "processing"})
            return
        if segment_minutes:
            await self.register_segments(file_name, segment_count, log_id, timed_output=timed_output)
            return
        formats = {}
        for extension in ("ts", "flv"):
            paths = [Path(f"{file_name}_{index}.{extension}") for index in range(1, segment_count + 1)]
            segments = [path for path in paths if path.is_file() and path.stat().st_size > 0]
            if segments:
                formats[extension] = segments
        if len(formats) > 1:
            logger.warning(self._log_message("录制流格式发生变化：TS 分片=%s，FLV 分片=%s；原文件已保留，请在视频处理中分别整理"),
                           len(formats.get("ts", [])), len(formats.get("flv", [])), extra={"event_code": "processing"})
            return
        if not formats:
            logger.warning(self._log_message("没有非空录制分片，未生成视频文件"), extra={"event_code": "processing"})
            return
        extension, segments = next(iter(formats.items()))
        try:
            await get_disk_guard(self.app).ensure_can_start(segments[0].parent, sum(path.stat().st_size for path in segments))
        except DiskSpaceError as exc:
            logger.warning(self._log_message("磁盘空间不足，暂停合并并保留原分片：%s"), exc, extra={"event_code": "disk_space"})
            return
        listing = Path(f"{file_name}_filelist.txt")
        merged = Path(f"{file_name}.{extension}")
        logger.info(self._log_message("开始合并录制文件：分片数=%s，输出=%s"), len(segments), merged, extra={"event_code": "processing"})
        return_code = await merge_segments(segments, merged, listing)
        if return_code != 0 or not merged.is_file() or merged.stat().st_size == 0:
            logger.warning(self._log_message("合并未成功：退出码=%s，目标=%s；原分片已保留"), return_code, merged, extra={"event_code": "processing"})
            return
        try:
            video = await self._video_metadata(merged)
            await self.repository.register_videos(self.room["id"], log_id, [video])
        except Exception:
            logger.exception(self._log_message("视频信息登记失败：文件=%s；合并文件和原分片均已保留"), merged, extra={"event_code": "database"})
            return
        logger.info(self._log_message("视频已保存并登记：文件=%s，大小=%.2f MiB，视频时长=%s 秒"),
                    merged, video["file_size"] / (1024 * 1024), video["duration"], extra={"event_code": "recording_saved"})
        try:
            listing.unlink()
            for segment in segments:
                segment.unlink()
        except OSError:
            logger.exception(self._log_message("视频已登记，但原分片清理未完成，请检查文件权限"), extra={"event_code": "processing"})
        logger.debug(self._log_message("录制文件整理流程结束"))

    async def register_segments(self, file_name, segment_count, log_id, *, timed_output=None, probe_durations=True):
        """登记已完成的非空分片，中断时可跳过时长探测。

        Args:
            file_name: 录制文件路径前缀。
            segment_count: 已知的最大分片编号。
            log_id: 录制日志 ID。
            timed_output: 可用于发现最新分片编号的跟踪器。
            probe_durations: 是否调用 FFprobe 读取时长。
        """
        if timed_output is not None:
            _, last_index = await asyncio.to_thread(timed_output.observation)
            segment_count = max(segment_count, last_index)
        videos = []
        for index in range(1, segment_count + 1):
            for extension in ("ts", "flv"):
                path = Path(f"{file_name}_{index}.{extension}")
                if path.is_file() and not path.is_symlink() and path.stat().st_size > 0:
                    videos.append(await self._video_metadata(path, probe_durations=probe_durations))
        if not videos:
            logger.warning(self._log_message("没有可登记的非空定时分片，请检查录制过程"), extra={"event_code": "processing"})
            return
        await self.repository.register_videos(self.room["id"], log_id, videos, deduplicate=True)
        logger.info(self._log_message("定时分片已独立保存并登记：有效文件数=%s，总大小=%.2f MiB，目录=%s，时长探测=%s"),
                    len(videos), sum(video["file_size"] for video in videos) / (1024 * 1024), Path(file_name).parent,
                    "已执行" if probe_durations else "已跳过", extra={"event_code": "recording_saved"})

    async def _video_metadata(self, path, *, probe_durations=True):
        duration = 0
        if probe_durations:
            try:
                duration = await probe_duration(path)
            except (OSError, ValueError, TypeError, TimeoutError) as exc:
                logger.warning(self._log_message("视频时长读取失败：文件=%s，原因=%s；文件仍会登记，时长记为 0"), path, exc,
                               extra={"event_code": "processing"})
        return {"file_name": path.name, "file_path": str(path.resolve()), "file_size": path.stat().st_size, "duration": duration}
