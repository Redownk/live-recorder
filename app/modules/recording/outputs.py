"""协调录制分片合并、媒体信息探测、视频登记及成功后的文件清理。"""

import asyncio
from pathlib import Path

from app.core.logger import get_logger
from app.modules.recording.disk import DiskSpaceError, get_disk_guard
from app.modules.recording.tasks import get_recording_tasks
from app.shared.media.concat import merge_segments
from app.shared.media.probe import probe_duration


logger = get_logger(__name__)


class RecordingOutput:
    """处理录制输出，只有成功登记视频后才清理原分片。"""

    def __init__(self, app, room, repository):
        self.app = app
        self.room = room
        self.repository = repository

    async def finalize(self, file_name, segment_count, log_id, *, segment_minutes=0, timed_output=None):
        """按录制设置合并分片或逐个登记定时分片。

        Args:
            file_name: 录制文件路径前缀。
            segment_count: 本轮可能存在的最大分片编号。
            log_id: 录制日志 ID。
            segment_minutes: 定时分片时长；为 0 时执行合并。
            timed_output: 当前定时分片跟踪器，允许为 None。
        """
        logger.info("开始后处理")
        key = (self.room["platform"], str(self.room["room_id"]))
        get_recording_tasks(self.app).phases[key] = "registering" if segment_minutes else "merging"
        if segment_count <= 0:
            logger.info("没有分段文件，跳过处理")
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
            logger.warning("录制流格式发生变化，保留全部 TS / FLV 分片，不自动合并")
            return
        if not formats:
            logger.info("没有有效分段文件，跳过处理")
            return
        extension, segments = next(iter(formats.items()))
        try:
            await get_disk_guard(self.app).ensure_can_start(segments[0].parent, sum(path.stat().st_size for path in segments))
        except DiskSpaceError as exc:
            logger.warning("%s", exc)
            return
        listing = Path(f"{file_name}_filelist.txt")
        merged = Path(f"{file_name}.{extension}")
        logger.info("开始合并分段")
        return_code = await merge_segments(segments, merged, listing)
        if return_code != 0 or not merged.is_file() or merged.stat().st_size == 0:
            logger.warning("合并失败，保留分段文件，退出码: %s", return_code, extra={"event_code": "processing"})
            return
        try:
            video = await self._video_metadata(merged)
            await self.repository.register_videos(self.room["id"], log_id, [video])
        except Exception:
            logger.exception("本地视频登记失败，保留录制文件")
            return
        logger.info("本地视频已保存: %s", merged)
        try:
            listing.unlink()
            for segment in segments:
                segment.unlink()
        except OSError:
            logger.exception("清理文件失败")
        logger.info("后处理完成")

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
        await self.repository.register_videos(self.room["id"], log_id, videos, deduplicate=True)
        logger.info("定时分片已独立保存，不执行合并")

    async def _video_metadata(self, path, *, probe_durations=True):
        duration = 0
        if probe_durations:
            try:
                duration = await probe_duration(path)
            except (OSError, ValueError, TypeError, TimeoutError) as exc:
                logger.warning("视频时长读取失败，保留文件并登记大小: %s", exc)
        return {"file_name": path.name, "file_path": str(path.resolve()), "file_size": path.stat().st_size, "duration": duration}
