"""采集录制进度和文件增长情况，为启动超时与录制停滞检测提供依据。"""


from pathlib import Path
from dataclasses import dataclass
from time import monotonic


class RecordingHealthError(RuntimeError):
    """表示录制健康检查失败且无法继续录制。"""

    pass


@dataclass
class RecordingRecoveryState:
    """保存一场录制的健康恢复次数、最近故障和预算耗尽状态。"""

    restart_count: int = 0
    last_error: str | None = None
    failed: bool = False

    def register_failure(self, message, max_restarts):
        """记录故障并申请一次恢复；预算已耗尽时返回 True。

        Args:
            message: 最近的健康故障说明。
            max_restarts: 本场录制允许执行的最大恢复次数。

        Returns:
            是否耗尽预算；耗尽后不再增加已执行次数。
        """
        self.last_error = message
        exhausted = self.restart_count >= max_restarts
        if exhausted:
            self.failed = True
        else:
            self.restart_count += 1
        return exhausted


class RecordingHealthSample:
    """跟踪文件增长和 FFmpeg 媒体时间，判断录制是否正常推进。"""

    def __init__(self, *, progress_expected=True):
        self.started_at = monotonic()
        self.last_growth = self.started_at
        self.last_progress = self.started_at
        self.file_size = 0
        self.media_time_us = 0
        self.has_file = False
        self.has_progress = False
        self.progress_expected = progress_expected

    def progress_line(self, line):
        key, separator, value = line.partition("=")
        if separator and key == "out_time_us":
            try:
                timestamp = int(value)
            except ValueError:
                return
            if timestamp > self.media_time_us:
                self.media_time_us = timestamp
                self.last_progress = monotonic()
                self.has_progress = True

    def file_observation(self, size):
        if size > self.file_size:
            self.last_growth = monotonic()
            self.has_file = True
        self.file_size = size

    def failure(self, options):
        """根据最近采样判断是否启动超时或录制停滞。

        Args:
            options: 包含启动超时和停滞超时秒数的录制配置。

        Returns:
            检测到故障时返回原因说明，否则返回 None。
        """
        now = monotonic()
        ready = self.has_file and (self.has_progress or not self.progress_expected)
        if not ready:
            if now - self.started_at >= options.health_startup_timeout_seconds:
                return "启动超时：未检测到有效文件写入和媒体时间推进"
            return None
        if now - self.last_growth >= options.health_stall_timeout_seconds:
            return "录制卡住：文件大小长时间未增长"
        if self.progress_expected and now - self.last_progress >= options.health_stall_timeout_seconds:
            return "录制卡住：FFmpeg 媒体时间长时间未推进"
        return None

    def snapshot(self, options, restart_count, last_error):
        now = monotonic()
        ready = self.has_file and (self.has_progress or not self.progress_expected)
        waiting = ready and (now - self.last_growth >= options.health_stall_timeout_seconds / 2
                            or (self.progress_expected and now - self.last_progress >= options.health_stall_timeout_seconds / 2))
        return {
            "state": "disabled" if not options.health_check_enabled else "waiting" if waiting else "healthy" if ready else "starting",
            "output_bytes": self.file_size,
            "file_idle_seconds": max(0, int(now - self.last_growth)),
            "progress_idle_seconds": max(0, int(now - self.last_progress)) if self.progress_expected else None,
            "media_seconds": self.media_time_us / 1000000,
            "restart_count": restart_count,
            "last_error": last_error,
        }


def recording_file_size(path):
    """读取录制文件大小。

    Args:
        path: 录制文件路径。

    Returns:
        文件字节数；文件不存在或无法读取时返回 0。
    """
    try:
        return Path(path).stat().st_size
    except OSError:
        return 0
