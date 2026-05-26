from app.services.platforms.recorder.bilibili_recorder import BilibiliRecorder
from app.services.platforms.recorder.douyin_recorder import DouyinRecorder
from app.services.platforms.recorder.douyu_recorder import DouyuRecorder

def create_recorder(app, room):
    platform = room.get("platform")
    if platform == "DOUYIN":
        return DouyinRecorder(app, room)
    if platform == "BILIBILI":
        return BilibiliRecorder(app, room)
    if platform == "DOUYU":
        return DouyuRecorder(app, room)
    return None