import re

from app.services.platforms.live_checkers.bilibili_live_checker import BiliLiveChecker
from app.services.platforms.live_checkers.douyin_live_checker import DouyinLiveChecker
from app.services.platforms.live_checkers.douyu_live_checker import DouyuLiveChecker


class LiveChecker:
    PLATFORM_PATTERNS = {
        "douyin": re.compile(r"https?://(?:(?:www|m|live|v)\.)?douyin\.com"),
        "bilibili": re.compile(r"https?://(b23\.tv|live\.bilibili\.com)"),
        "douyu": re.compile(r"https?://(?:(?:www|m)\.)?douyu\.com"),
    }

    @staticmethod
    def detect_platform(url: str) -> str:
        """
        根据 URL 判断平台
        """
        for name, pattern in LiveChecker.PLATFORM_PATTERNS.items():
            if pattern.search(url):
                return name

        raise ValueError("不支持的直播平台")

    @staticmethod
    async def check(url: str) -> dict:
        """
        根据 URL 检测直播信息
        """

        platform = LiveChecker.detect_platform(url)

        if platform == "douyin":
            return await DouyinLiveChecker.get_user_info(url)
        if platform == "bilibili":
            return await BiliLiveChecker.get_user_info(url)
        if platform == "douyu":
            return await DouyuLiveChecker.get_user_info(url)

        raise ValueError("平台暂未实现")
