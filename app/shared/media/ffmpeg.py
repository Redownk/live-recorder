"""按环境变量、内置工具和系统路径的顺序定位 FFmpeg。"""

import os
import shutil

from app.core.paths import RESOURCE_DIR

def get_ffmpeg_path():
    """查找可用的 FFmpeg 可执行文件。

    Returns:
        环境变量指定、程序内置或系统 PATH 中的 FFmpeg 路径。

    Raises:
        RuntimeError: 指定路径不是文件，或未找到 FFmpeg。
    """
    ffmpeg_path = os.getenv("FFMPEG_PATH")

    if ffmpeg_path:
        if os.path.isfile(ffmpeg_path):
            return ffmpeg_path
        else:
            raise RuntimeError(
                f"FFMPEG_PATH 已配置但文件不存在: {ffmpeg_path}"
            )

    bundled_path = RESOURCE_DIR / "tools" / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if bundled_path.is_file():
        return str(bundled_path)

    ffmpeg_cmd = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    system_path = shutil.which(ffmpeg_cmd)

    if system_path:
        return system_path

    raise RuntimeError(
        "未检测到 ffmpeg，请先安装 ffmpeg 并加入系统环境变量。\n"
        "Windows: https://www.gyan.dev/ffmpeg/builds/\n"
        "Mac: brew install ffmpeg\n"
        "Linux: sudo apt install ffmpeg"
    )
