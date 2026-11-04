"""管理录制 FFmpeg 进程及进度、错误输出和健康采样任务。"""

import asyncio

from app.core.logger import get_logger
from app.modules.recording.health import RecordingHealthSample, recording_file_size
from app.modules.recording.segments import TimedSegments
from app.shared.media.process import stop_process


logger = get_logger(__name__)


async def spawn_recording_process(command, segment_minutes=0):
    """启动带进度输出的录制进程，返回进程及可选的定时分片跟踪器。

    Args:
        command: FFmpeg 命令，最后一项为输出文件路径。
        segment_minutes: 每个定时分片的分钟数；为 0 时不启用定时分片。

    Returns:
        异步子进程和 TimedSegments 实例或 None 组成的元组。
    """
    timed_output = TimedSegments(command[-1]) if segment_minutes else None
    if timed_output is not None:
        command = timed_output.command(command, segment_minutes * 60)
    command = [command[0], "-progress", "pipe:1", "-stats_period", "1", "-nostats", *command[1:]]
    process = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    return process, timed_output


class RecordingProcessMonitor:
    """以回调提供配置和采样结果，不依赖录制器或数据库。"""

    def __init__(self, *, options, on_sample, timed_output=None):
        self.options = options
        self.on_sample = on_sample
        self.timed_output = timed_output
        self.health_error = None

    async def wait(self, process, output_file):
        """监控进程输出和健康信号，退出时回收进程及所有读取任务。

        Args:
            process: 正在录制的异步子进程。
            output_file: 当前输出文件路径。

        Returns:
            子进程退出码，健康失败原因另存于 health_error。
        """
        self.health_error = None
        stream = getattr(process, "stdout", None)
        sample = RecordingHealthSample(progress_expected=stream is not None)
        errors = bytearray()
        current_index = self.timed_output.first_index if self.timed_output else 0

        def publish():
            self.on_sample(sample)

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
        try:
            publish()
            while True:
                done, _ = await asyncio.wait({waiting}, timeout=5)
                if done:
                    return await waiting
                if self.timed_output is not None:
                    size, index = await asyncio.to_thread(self.timed_output.observation)
                    if index != current_index:
                        current_index = index
                        sample.media_time_us = 0
                    sample.file_observation(size)
                else:
                    sample.file_observation(await asyncio.to_thread(recording_file_size, output_file))
                if waiting.done():
                    return await waiting
                options = self.options()
                publish()
                if options.health_check_enabled:
                    failure = sample.failure(options)
                    if failure:
                        self.health_error = failure
                        await stop_process(process)
                        return await waiting
        finally:
            # 取消等待任务前先回收子进程，覆盖手动停止和磁盘保护触发的取消。
            await stop_process(process)
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
                    and self.health_error is None):
                logger.warning("FFmpeg 异常退出: %s", errors.decode("utf-8", errors="replace") or "无错误输出",
                               extra={"event_code": "ffmpeg_exit"})
