"""将录制画质档位映射为可用直播流，并选择抖音播放地址。"""


def quality_index(count, quality):
    """计算画质档位对应的直播流索引。

    Args:
        count: 可用直播流数量，调用方应保证至少为 1。
        quality: 画质档位，可选 best、high、medium 或 low。
            直播流须按画质从高到低排列。

    Returns:
        从 0 开始的直播流索引。只有一条流时返回 0。
    """
    if count <= 1 or quality == "best":
        return 0
    return {"high": 1, "medium": max(1, count // 2), "low": count - 1}[quality]


def douyin_stream(live_info, quality):
    """按画质档位选择抖音直播流地址，优先使用 HLS。

    Args:
        live_info: 包含 streams 字典的直播信息，各流可提供 hls 和 flv 地址。
        quality: 画质档位，可选 best、high、medium 或 low。

    Returns:
        选中直播流的 HLS 或 FLV 地址。无可用视频流时回退到音频流。

    Raises:
        ValueError: 没有可用的直播流。
    """
    streams = live_info.get("streams", {})
    # 固定画质顺序，避免平台响应中字典的排列顺序影响档位选择。
    available = [streams[key] for key in ("real_origin", "origin", "uhd", "hd", "sd", "ld")
                 if key in streams and (streams[key].get("hls") or streams[key].get("flv"))]
    if not available and streams.get("ao"):
        available = [streams["ao"]]
    if not available:
        raise ValueError("没有可用直播流")
    stream = available[quality_index(len(available), quality)]
    return stream.get("hls") or stream["flv"]
