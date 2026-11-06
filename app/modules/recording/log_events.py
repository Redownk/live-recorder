"""提供直播检测日志的重复抑制和易读的房间标识。"""

from collections import OrderedDict
from dataclasses import dataclass
from time import monotonic


PLATFORM_NAMES = {"DOUYIN": "抖音", "BILIBILI": "哔哩哔哩", "DOUYU": "斗鱼"}


def room_label(room):
    """生成单行房间标识，限制主播或备注长度，避免影响日志阅读。"""
    platform = PLATFORM_NAMES.get(room.get("platform"), room.get("platform", "未知平台"))
    name = " ".join(str(room.get("remark") or room.get("owner") or "未命名直播间").split())[:80]
    room_id = " ".join(str(room.get("room_id", "")).split())[:128]
    return f"[{platform} / {name} / 房间 {room_id}]"


@dataclass(frozen=True)
class CheckLogDecision:
    """记录本次是否输出、合并的重复次数及是否从失败中恢复。"""

    emit: bool
    suppressed: int = 0
    recovered: bool = False


class CheckLogLimiter:
    """对相同房间的相同结果最多每五分钟输出一次，状态变化立即输出。"""

    def __init__(self, *, interval=300, capacity=1000, clock=monotonic):
        self.interval = interval
        self.capacity = capacity
        self.clock = clock
        self.states = OrderedDict()

    def observe(self, key, state, *, detail="", force=False):
        """记录检测结果；手动操作强制输出，缓存按最近使用顺序限制大小。"""
        now = self.clock()
        previous = self.states.pop(key, None)
        fingerprint = (state, detail)
        if previous is not None and previous[0] == fingerprint and not force and now - previous[1] < self.interval:
            self.states[key] = (fingerprint, previous[1], previous[2] + 1)
            return CheckLogDecision(False)
        suppressed = previous[2] if previous is not None and previous[0] == fingerprint else 0
        recovered = previous is not None and previous[0][0] in {"error", "disk_blocked"} and state in {"offline", "live"}
        self.states[key] = (fingerprint, now, 0)
        while len(self.states) > self.capacity:
            self.states.popitem(last=False)
        return CheckLogDecision(True, suppressed, recovered)
