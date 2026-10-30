def quality_index(count, quality):
    if count <= 1 or quality == "best":
        return 0
    return {"high": 1, "medium": max(1, count // 2), "low": count - 1}[quality]


def douyin_stream(live_info, quality):
    streams = live_info.get("streams", {})
    available = [streams[key] for key in ("real_origin", "origin", "uhd", "hd", "sd", "ld")
                 if key in streams and (streams[key].get("hls") or streams[key].get("flv"))]
    if not available and streams.get("ao"):
        available = [streams["ao"]]
    if not available:
        raise ValueError("没有可用直播流")
    stream = available[quality_index(len(available), quality)]
    return stream.get("hls") or stream["flv"]
