"""根据直播间的平台标识创建对应的录制器。"""


from app.services.platforms.recorder.bilibili_recorder import BilibiliRecorder
from app.services.platforms.recorder.douyin_recorder import DouyinRecorder
from app.services.platforms.recorder.douyu_recorder import DouyuRecorder

def create_recorder(app, room):
    """根据平台标识创建直播间录制器。

    Args:
        app: 提供数据库和录制管理器的应用实例。
        room: 直播间信息，其中 platform 使用大写平台标识。

    Returns:
        对应平台的录制器；平台不受支持时返回 None。
    """
    platform = room.get("platform")
    if platform == "DOUYIN":
        return DouyinRecorder(app, room)
    if platform == "BILIBILI":
        return BilibiliRecorder(app, room)
    if platform == "DOUYU":
        return DouyuRecorder(app, room)
    return None
