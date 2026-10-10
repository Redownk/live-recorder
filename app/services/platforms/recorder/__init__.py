import os
import shutil

from app.core.paths import RESOURCE_DIR

def get_ffmpeg_path():
    # 1️⃣ 优先读取环境变量
    ffmpeg_path = os.getenv("FFMPEG_PATH")

    if ffmpeg_path:
        if os.path.exists(ffmpeg_path):
            return ffmpeg_path
        else:
            raise RuntimeError(
                f"FFMPEG_PATH 已配置但文件不存在: {ffmpeg_path}"
            )

    bundled_path = RESOURCE_DIR / "tools" / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if bundled_path.is_file():
        return str(bundled_path)

    # 2️⃣ 没有环境变量，尝试从系统 PATH 查找
    ffmpeg_cmd = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    system_path = shutil.which(ffmpeg_cmd)

    if system_path:
        return system_path

    # 3️⃣ 完全找不到
    raise RuntimeError(
        "未检测到 ffmpeg，请先安装 ffmpeg 并加入系统环境变量。\n"
        "Windows: https://www.gyan.dev/ffmpeg/builds/\n"
        "Mac: brew install ffmpeg\n"
        "Linux: sudo apt install ffmpeg"
    )
