"""校验平台 Cookie，并原子更新配置文件与进程内配置。"""

from copy import deepcopy
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock

import yaml

from app.core.config import CONFIG_PATH, local_config
from app.core.logger import refresh_secrets


PLATFORM_NAMES = {"douyin": "抖音", "bilibili": "哔哩哔哩", "douyu": "斗鱼"}
_write_lock = Lock()


def cookie_status(platform):
    """返回平台配置状态，不返回 Cookie 原文。"""
    value = local_config.get("platforms", {}).get(platform, {}).get("cookie", "")
    return {"platform": platform, "name": PLATFORM_NAMES[platform], "configured": bool(value)}


def normalize_cookie(value):
    """校验可用于 HTTP 请求头的 Cookie，支持粘贴 Cookie: 前缀。

    Args:
        value: 用户输入的 Cookie 字符串。

    Returns:
        去除前缀和首尾空白的 Cookie。

    Raises:
        ValueError: 内容过长或包含请求头不支持的字符。
    """
    if not isinstance(value, str) or len(value) > 16384:
        raise ValueError("Cookie 必须为文本且不能超过 16384 个字符")
    value = value.strip()
    if value.lower().startswith("cookie:"):
        value = value[7:].strip()
    if any(ord(character) < 32 or ord(character) > 126 for character in value):
        raise ValueError("Cookie 不能包含换行、控制字符或非 ASCII 字符")
    return value


def save_platform_cookie(platform, value):
    """保存单个平台 Cookie，写入成功后才更新运行时配置。

    Args:
        platform: 支持的小写平台标识。
        value: 新 Cookie，空字符串表示清除。

    Returns:
        不含 Cookie 原文的平台配置状态。
    """
    if platform not in PLATFORM_NAMES:
        raise ValueError("不支持的平台")
    value = normalize_cookie(value)
    with _write_lock:
        config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) if CONFIG_PATH.exists() else deepcopy(local_config)
        if config is None:
            config = {}
        if not isinstance(config, dict):
            raise ValueError("配置文件格式不正确")
        platforms = config.setdefault("platforms", {})
        if not isinstance(platforms, dict) or not isinstance(platforms.get(platform, {}), dict):
            raise ValueError("平台配置格式不正确")
        platform_config = platforms.setdefault(platform, {})
        platform_config["cookie"] = value
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with NamedTemporaryFile(mode="w", encoding="utf-8", dir=CONFIG_PATH.parent, prefix=".config-", suffix=".tmp", delete=False) as file:
                temporary = Path(file.name)
                yaml.safe_dump(config, file, allow_unicode=True, sort_keys=False)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, CONFIG_PATH)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        # 保持根字典的引用不变，使各检测器在下一次构造请求头时读取新值。
        current = dict(local_config.get("platforms", {}))
        current[platform] = {**current.get(platform, {}), "cookie": value}
        local_config["platforms"] = current
        refresh_secrets()
    return cookie_status(platform)
