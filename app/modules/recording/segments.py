"""构造 FFmpeg 定时分片参数，并追踪分片文件和进度。"""


from pathlib import Path
import re


class TimedSegments:
    """管理同一录制输出前缀下的编号分片及 FFmpeg 分片参数。"""

    def __init__(self, first_file):
        first = Path(first_file)
        match = re.fullmatch(r"(.+)_(\d+)", first.stem)
        if match is None or first.suffix not in {".ts", ".flv"}:
            raise ValueError("无效的录制分片路径")
        self.prefix = first.with_name(match[1])
        self.first_index = int(match[2])
        self.extension = first.suffix
        self.pattern = re.compile(re.escape(self.prefix.name) + r"_(\d+)" + re.escape(self.extension) + "$")

    def files(self):
        result = []
        for path in self.prefix.parent.iterdir():
            match = self.pattern.fullmatch(path.name)
            if match and int(match[1]) >= self.first_index and path.is_file() and not path.is_symlink():
                result.append((int(match[1]), path))
        return sorted(result)

    def observation(self):
        """返回现有分片的总字节数和最新编号，无文件时使用初始编号。"""
        files = self.files()
        size = sum(path.stat().st_size for _, path in files)
        index = files[-1][0] if files else self.first_index
        return size, index

    def command(self, command, seconds):
        """将单文件录制命令转换为定时分片命令。

        Args:
            command: 以输出格式参数和文件路径结尾的 FFmpeg 参数列表。
            seconds: 每个分片的目标时长，单位为秒。

        Returns:
            使用 segment 输出格式的新命令参数列表。

        Raises:
            ValueError: 原命令缺少预期的输出格式参数。
        """
        if len(command) < 3 or command[-3] != "-f":
            raise ValueError("录制输出缺少格式参数")
        # 先转义路径中的百分号，避免被 FFmpeg 当作分片编号占位符。
        pattern = str(self.prefix).replace("%", "%%") + "_%d" + self.extension
        return [*command[:-3], "-f", "segment", "-segment_time", str(seconds), "-segment_start_number", str(self.first_index),
                "-reset_timestamps", "1", "-segment_format", "mpegts" if self.extension == ".ts" else "flv", pattern]
