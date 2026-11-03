"""构造平台录制器共用的 FFmpeg 直播流复制命令。"""


def build_recording_command(executable, stream_url, output_prefix, segment_index, headers):
    """根据直播流格式生成输出路径和录制命令。

    Args:
        executable: FFmpeg 可执行文件路径。
        stream_url: 直播流地址。
        output_prefix: 录制输出路径前缀，不含分片编号和扩展名。
        segment_index: 当前分片编号。
        headers: 以 CRLF 分隔的 HTTP 请求头字符串。

    Returns:
        输出文件路径与命令参数列表组成的元组。HLS 流写入 TS，其他流写入 FLV。
    """
    is_hls = ".m3u8" in stream_url.lower()
    extension, container = ("ts", "mpegts") if is_hls else ("flv", "flv")
    output_file = f"{output_prefix}_{segment_index}.{extension}"
    command = [
        executable,
        "-nostdin", "-n",
        "-headers", headers,
        "-i", stream_url,
        "-c", "copy",
        "-f", container,
        output_file,
    ]
    return output_file, command
