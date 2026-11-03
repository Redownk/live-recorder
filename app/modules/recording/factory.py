"""根据直播间的平台标识创建对应的录制器。"""


from app.services.platforms.bilibili.recorder import BilibiliRecorder
from app.services.platforms.douyin.recorder import DouyinRecorder
from app.services.platforms.douyu.recorder import DouyuRecorder


RECORDERS = {
    "DOUYIN": DouyinRecorder,
    "BILIBILI": BilibiliRecorder,
    "DOUYU": DouyuRecorder,
}


def create_recorder(app, room):
    """根据平台标识创建直播间录制器。

    Args:
        app: 提供数据库和录制管理器的应用实例。
        room: 直播间信息，其中 platform 使用大写平台标识。

    Returns:
        对应平台的录制器；平台不受支持时返回 None。
    """
    recorder_type = RECORDERS.get(room.get("platform"))
    return recorder_type(app, room) if recorder_type is not None else None
