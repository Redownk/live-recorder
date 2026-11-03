"""生成平台请求使用的桌面端或移动端 User-Agent。"""

import random


def random_user_agent(device: str = 'desktop') -> str:
    """生成 Chrome 浏览器请求头标识。

    Args:
        device: mobile 生成 Android 标识，其他值生成 Windows 桌面标识。

    Returns:
        User-Agent 字符串。
    """
    chrome_version = random.randint(100, 120)
    if device == 'mobile':
        android_version = random.randint(9, 14)
        mobile = random.choice([
            'SM-G981B', 'SM-G9910', 'SM-S9080', 'SM-S9110', 'SM-S921B',
            'Pixel 5', 'Pixel 6', 'Pixel 7', 'Pixel 7 Pro', 'Pixel 8',
        ])
        return f'Mozilla/5.0 (Linux; Android {android_version}; {mobile}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version}.0.0.0 Mobile Safari/537.36'
    return f'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version}.0.0.0 Safari/537.36'
