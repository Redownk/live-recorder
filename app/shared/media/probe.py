"""使用 FFprobe 读取媒体时长及音视频轨道信息。"""

import json
import math
from pathlib import Path

from app.shared.media.ffmpeg import get_ffprobe_path
from app.shared.media.process import capture_output


async def probe_duration(path):
    """读取媒体时长，缺失或无效的时长返回 0。

    Args:
        path: 待探测的本地媒体文件路径。

    Returns:
        以秒为单位的整数时长。
    """
    stdout = await capture_output(
        get_ffprobe_path(), "-v", "error", "-show_entries", "format=duration",
        "-of", "json", str(path), timeout=15,
    )
    value = float(json.loads(stdout).get("format", {}).get("duration") or 0)
    return int(value) if math.isfinite(value) and value > 0 else 0


async def probe_video(path, *, capture=capture_output):
    """读取视频时长及用于判断合并兼容性的轨道签名。

    Args:
        path: 待探测的本地视频路径。
        capture: 异步命令输出采集函数，返回标准输出字节。

    Returns:
        视频时长和音视频轨道签名组成的元组。

    Raises:
        ValueError: 文件没有视频轨道或没有有效时长。
    """
    path = Path(path)
    data = json.loads(await capture(
        get_ffprobe_path(), "-v", "error", "-protocol_whitelist", "file,pipe",
        "-show_streams", "-show_format", "-of", "json", str(path),
    ))
    streams = data.get("streams", [])
    if not any(stream.get("codec_type") == "video" for stream in streams):
        raise ValueError(f"没有视频轨道: {path.name}")
    duration = float(data.get("format", {}).get("duration") or 0)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError(f"无法获取视频时长: {path.name}")
    fields = (
        "codec_type", "codec_name", "profile", "level", "width", "height", "pix_fmt",
        "sample_aspect_ratio", "r_frame_rate", "sample_rate", "channels", "channel_layout",
        "time_base", "extradata_size",
    )
    signature = [tuple(stream.get(key) for key in fields) for stream in streams
                 if stream.get("codec_type") in ("video", "audio")]
    return duration, signature
