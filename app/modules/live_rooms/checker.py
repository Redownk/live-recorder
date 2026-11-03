"""根据直播链接识别平台，并将信息查询分发到对应的平台检测器。"""


import re

from app.services.platforms.bilibili.checker import BiliLiveChecker
from app.services.platforms.douyin.checker import DouyinLiveChecker
from app.services.platforms.douyu.checker import DouyuLiveChecker


class LiveChecker:
    """识别直播链接的平台，并调用对应的平台信息查询实现。"""

    PLATFORM_PATTERNS = {
        "douyin": re.compile(r"https?://(?:(?:www|m|live|v)\.)?douyin\.com"),
        "bilibili": re.compile(r"https?://(b23\.tv|live\.bilibili\.com)"),
        "douyu": re.compile(r"https?://(?:(?:www|m)\.)?douyu\.com"),
    }

    @staticmethod
    def detect_platform(url: str) -> str:
        """根据直播链接识别平台。

        Args:
            url: 待识别的直播链接。

        Returns:
            小写平台标识 douyin、bilibili 或 douyu。

        Raises:
            ValueError: 链接不属于受支持的平台。
        """
        for name, pattern in LiveChecker.PLATFORM_PATTERNS.items():
            if pattern.search(url):
                return name

        raise ValueError("不支持的直播平台")

    @staticmethod
    async def check(url: str) -> dict:
        """调用对应平台的检测器查询直播间信息。

        Args:
            url: 待查询的直播链接。

        Returns:
            平台检测器的查询结果；具体字段和失败结果由平台实现决定。

        Raises:
            ValueError: 链接平台不受支持或尚未实现。
        """

        platform = LiveChecker.detect_platform(url)

        if platform == "douyin":
            return await DouyinLiveChecker.get_user_info(url)
        if platform == "bilibili":
            return await BiliLiveChecker.get_user_info(url)
        if platform == "douyu":
            return await DouyuLiveChecker.get_user_info(url)

        raise ValueError("平台暂未实现")
