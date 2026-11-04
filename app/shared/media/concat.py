"""生成 FFconcat 清单，并执行无转码的媒体分片合并。"""

import asyncio
from pathlib import Path

from app.shared.media.ffmpeg import get_ffmpeg_path
from app.shared.media.process import stop_process


def concat_text(paths, durations=None):
    """生成 FFconcat 清单，转义文件名中的单引号。

    Args:
        paths: 按合并顺序排列的文件路径。
        durations: 可选的各文件时长，单位为秒。

    Returns:
        带 FFconcat 文件头的清单文本。
    """
    lines = ["ffconcat version 1.0"]
    for index, path in enumerate(paths):
        escaped = Path(path).as_posix().replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
        if durations is not None:
            lines.append(f"duration {durations[index]:.6f}")
    return "\n".join(lines) + "\n"


async def merge_segments(paths, output, listing):
    """合并媒体分片，不覆盖已有输出文件。

    Args:
        paths: 按合并顺序排列的本地分片路径。
        output: 合并输出路径。
        listing: 临时 FFconcat 清单路径，由调用方决定何时删除。

    Returns:
        FFmpeg 退出码。
    """
    Path(listing).write_text(concat_text([Path(path).resolve() for path in paths]), encoding="utf-8")
    process = await asyncio.create_subprocess_exec(
        get_ffmpeg_path(), "-nostdin", "-n", "-f", "concat", "-safe", "0",
        "-i", str(listing), "-c", "copy", str(output),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        return await process.wait()
    finally:
        await stop_process(process)
