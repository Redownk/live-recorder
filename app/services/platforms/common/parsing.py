"""提供平台响应解析和正则匹配工具。"""

import json
import re
from typing import Any


def match1(text: str, *patterns: str) -> str | None | list[str]:
    """提取正则表达式的第一个捕获组。

    Args:
        text: 待匹配文本。
        *patterns: 含捕获组的正则表达式。

    Returns:
        单个表达式返回匹配值或 None；多个表达式返回成功匹配的值列表。
    """
    if len(patterns) == 1:
        pattern = patterns[0]
        match = re.search(pattern, text)
        if match:
            return match.group(1)
        else:
            return None
    else:
        ret = []
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                ret.append(match.group(1))
        return ret


def json_loads(text: str | None) -> Any:
    """解析平台返回的 JSON 内容。

    Args:
        text: 待解析的 JSON 文本。

    Returns:
        JSON 解码结果，可能为字典、列表或标量。

    Raises:
        ValueError: 内容为空或不是合法 JSON。
    """
    if not text:
        raise ValueError("Invalid JSON: None")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        # 错误消息不附带原始响应，避免平台返回的敏感数据进入日志。
        raise ValueError("Invalid JSON response") from e
