from pathlib import Path
import re


class TimedSegments:
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
        files = self.files()
        size = sum(path.stat().st_size for _, path in files)
        index = files[-1][0] if files else self.first_index
        return size, index

    def command(self, command, seconds):
        if len(command) < 3 or command[-3] != "-f":
            raise ValueError("录制输出缺少格式参数")
        # Escape literal percent characters before adding FFmpeg's numeric placeholder.
        pattern = str(self.prefix).replace("%", "%%") + "_%d" + self.extension
        return [*command[:-3], "-f", "segment", "-segment_time", str(seconds), "-segment_start_number", str(self.first_index),
                "-reset_timestamps", "1", "-segment_format", "mpegts" if self.extension == ".ts" else "flv", pattern]
