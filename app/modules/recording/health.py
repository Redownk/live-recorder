from pathlib import Path
from time import monotonic


class RecordingHealthError(RuntimeError):
    pass


class RecordingHealthSample:
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
    try:
        return Path(path).stat().st_size
    except OSError:
        return 0
