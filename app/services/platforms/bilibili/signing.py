"""维护哔哩哔哩 WBI 密钥并生成请求签名。"""

import hashlib
import logging
import time
from urllib.parse import quote, urlencode


logger = logging.getLogger(__name__)


class Wbi:
    """缓存平台下发的 WBI 密钥，并使用密钥签署请求参数。"""

    WTS = "wts"
    W_RID = "w_rid"
    UPDATE_INTERVAL = 2 * 60 * 60

    KEY_MAP = [
        46, 47, 18, 2,  53, 8,  23, 32, 15, 50, 10, 31, 58, 3,  45, 35,
        27, 43, 5,  49, 33, 9,  42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
        37, 48, 7,  16, 24, 55, 40, 61, 26, 17, 0,  1,  60, 51, 30, 4,
        22, 25, 54, 21, 56, 59, 6,  63, 57, 62, 11, 36, 20, 34, 44, 52,
    ]

    def __init__(self):
        self.key = None
        self.last_update = 0

    def update_key(self, img, sub):
        """更新密钥和最近刷新时间。

        Args:
            img: 平台返回的图片密钥。
            sub: 平台返回的辅助密钥。
        """
        KEY_LENGTH = 32
        full = img + sub
        key = [full[self.KEY_MAP[i]] for i in range(KEY_LENGTH)]
        self.key = ''.join(key)
        self.last_update = int(time.time())
        logger.info("Updated wbi key successfully")

    def sign(self, query: dict, ts: int = 0):
        """原地添加请求时间戳和 WBI 签名。

        Args:
            query: 值为字符串的请求参数字典，将写入 wts 和 w_rid。
            ts: Unix 时间戳，单位为秒；为 0 时使用当前时间。

        Raises:
            ValueError: 尚未设置签名密钥。
        """
        if self.key is None:
            raise ValueError("Key is not set.")

        ts = ts or int(time.time())
        ts_str = str(ts)

        sanitized_query = {
            k: ''.join(c for c in v if c not in "!\'()*")
            for k, v in query.items()
        }
        sanitized_query[self.WTS] = ts_str
        sorted_query = dict(sorted(sanitized_query.items()))
        content_string = urlencode(sorted_query, quote_via=quote)

        md5 = hashlib.md5()
        md5.update((content_string + self.key).encode('utf-8'))
        sign = md5.hexdigest()

        query[self.W_RID] = sign
        query[self.WTS] = ts_str


wbi = Wbi()
