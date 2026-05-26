import asyncio
import hashlib
import logging
import time
from typing import Any, Optional, Union
from urllib.parse import parse_qs

import httpx
from requests.utils import DEFAULT_ACCEPT_ENCODING

from app.core.config import local_config
from app.services.platforms.common.util import client
from app.services.platforms.live_checkers import random_user_agent, match1, json_loads


logger = logging.getLogger("DouyuLiveChecker")

DOUYU_DEFAULT_DID = "10000000000000000000000000001501"
DOUYU_WEB_DOMAIN = "www.douyu.com"
DOUYU_PLAY_DOMAIN = "playweb.douyucdn.cn"
DOUYU_MOBILE_DOMAIN = "m.douyu.com"


class DouyuLiveChecker:
    fake_headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "accept-encoding": DEFAULT_ACCEPT_ENCODING,
        "accept-language": "zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3",
        "user-agent": random_user_agent(),
        "referer": f"https://{DOUYU_WEB_DOMAIN}/",
        "cookie": "",
    }

    @staticmethod
    def build_fake_headers() -> dict:
        fake_headers = DouyuLiveChecker.fake_headers
        douyu_config = local_config.get("platforms", {}).get("douyu", {})
        fake_headers["user-agent"] = random_user_agent()
        fake_headers["referer"] = f"https://{DOUYU_WEB_DOMAIN}/"
        fake_headers["cookie"] = douyu_config.get("cookie", "") or ""
        return fake_headers

    @staticmethod
    def is_jsengine_available() -> bool:
        try:
            import jsengine  # type: ignore # noqa: F401

            return True
        except Exception:
            return False

    @staticmethod
    async def get_user_info(url: str):
        try:
            room_id = str(match1(url, r"rid=(\d+)"))
            if not room_id.isdigit():
                room_id = await DouyuLiveChecker.get_real_rid(url)
            if not room_id or not room_id.isdigit():
                raise ValueError("房间号解析失败")

            room_info = await DouyuLiveChecker.get_room_info(room_id)
            room_data = room_info.get("room") or {}
            if not room_data:
                raise ValueError("房间信息为空")

            if room_data.get("isVip") == 1:
                async with DouyuUtils._lock:
                    DouyuUtils.VipRoom.add(room_id)

            owner = (
                room_data.get("nickname")
                or room_data.get("owner_name")
                or room_data.get("show_nick")
                or ""
            )
            avatar = (
                # room_data.get("avatar")
                # or room_data.get("owner_avatar")
                # or room_data.get("room_src")
                # or ""
                room_data.get("owner_avatar")
            )
            # sec_uid = (
            #     str(room_data.get("owner_uid"))
            #     if room_data.get("owner_uid") is not None
            #     else str(room_data.get("up_id") or room_data.get("uid") or room_id)
            # )

            return {
                "platform": "DOUYU",
                "roomId": str(room_data.get("room_id") or room_data.get("roomId") or room_id),
                "secUid": str(room_data.get("room_id") or room_data.get("roomId") or room_id),
                "owner": owner,
                "avatar": avatar,
                "result": "success",
            }
        except Exception:
            logger.exception("获取斗鱼直播间信息失败")
            return {
                "platform": "DOUYU",
                "available": False,
                "result": "error",
            }

    @staticmethod
    async def get_room_info(room_id: str) -> dict:
        headers = DouyuLiveChecker.build_fake_headers()
        resp = await client.get(
            f"https://{DOUYU_WEB_DOMAIN}/betard/{room_id}",
            headers=headers,
        )
        resp.raise_for_status()
        return json_loads(resp.text)

    @staticmethod
    async def get_real_rid(url: str) -> str:
        rid = url.split("douyu.com/")[1].split("/")[0].split("?")[0] or match1(url, r"douyu.com/(\d+)")
        resp = await client.get(
            f"https://{DOUYU_MOBILE_DOMAIN}/{rid}",
            headers={"User-Agent": random_user_agent("mobile")},
        )
        real_rid = match1(resp.text, r'roomInfo":{"rid":(\d+)')
        return str(real_rid)

    @staticmethod
    async def aclac_sign(rid: Union[str, int], headers: dict[str, str]) -> dict[str, Any]:
        if not DouyuLiveChecker.is_jsengine_available():
            raise RuntimeError("jsengine not found")

        import jsengine  # type: ignore

        ctx = jsengine.jsengine()
        h5enc_url = f"https://{DOUYU_WEB_DOMAIN}/swf_api/homeH5Enc?rids={rid}"
        js_enc = (
            await client.get(h5enc_url, headers=headers)
        ).json()["data"][f"room{rid}"]
        js_enc = js_enc.replace("return eval", "return [strc, vdwdae325w_64we];")

        sign_fun, sign_v = ctx.eval(f"{js_enc};ub98484234();")

        tt = str(int(time.time()))
        did = hashlib.md5(tt.encode("utf-8")).hexdigest()
        rb = hashlib.md5(f"{rid}{did}{tt}{sign_v}".encode("utf-8")).hexdigest()
        sign_fun = sign_fun.rstrip(";").replace("CryptoJS.MD5(cb).toString()", f'"{rb}"')
        sign_fun += f'("{rid}","{did}","{tt}");'

        return parse_qs(ctx.eval(sign_fun))

    @staticmethod
    async def get_play_info(
        room_id: Union[str, int],
        rate: int = 0,
        cdn: Optional[str] = None,
        did: str = DOUYU_DEFAULT_DID,
    ) -> dict[str, Any]:
        if isinstance(room_id, int):
            room_id = str(room_id)

        headers = DouyuLiveChecker.build_fake_headers()
        douyu_config = local_config.get("platforms", {}).get("douyu", {})
        req_query = {
            "cdn": cdn or douyu_config.get("cdn", "hw-h5"),
            "rate": str(rate if rate is not None else douyu_config.get("rate", 0)),
            "ver": "Douyu_new",
            "iar": "0",
            "ive": "0",
            "rid": room_id,
            "hevc": "0",
            "fa": "0",
            "sov": "0",
        }

        room_info = await DouyuLiveChecker.get_room_info(room_id)
        room_data = room_info.get("room") or {}
        if room_data.get("isVip") == 1:
            async with DouyuUtils._lock:
                DouyuUtils.VipRoom.add(room_id)

        for _ in range(2):
            try:
                if DouyuLiveChecker.is_jsengine_available() and room_id in DouyuUtils.VipRoom:
                    sign = await DouyuLiveChecker.aclac_sign(room_id, headers)
                    payload = {**req_query, **sign}
                    url = f"https://{DOUYU_PLAY_DOMAIN}/lapi/live/getH5Play/{room_id}"
                    rsp = await client.get(url, headers=headers, params=payload)
                else:
                    sign = await DouyuUtils.sign(
                        sign_type="stream",
                        ts=int(time.time()),
                        did=did,
                        rid=room_id,
                    )
                    payload = {
                        **req_query,
                        "enc_data": sign["key"]["enc_data"],
                        "tt": sign["ts"],
                        "did": did,
                        "auth": sign["auth"],
                    }
                    url = f"https://{DOUYU_WEB_DOMAIN}/lapi/live/getH5PlayV1/{room_id}"
                    rsp = await client.post(
                        url,
                        headers={**headers, "user-agent": DouyuUtils.UserAgent or headers["user-agent"]},
                        data=payload,
                    )

                rsp.raise_for_status()
                play_data = json_loads(rsp.text)
                if not play_data:
                    raise RuntimeError("获取播放信息失败")
                if play_data.get("error") != 0 or not play_data.get("data", {}):
                    err = play_data.get("error")
                    msg = play_data.get("msg", "")
                    if err == -5:
                        raise RuntimeError("[closeRoom] 主播未开播")
                    if err == -9:
                        raise RuntimeError("[room_bus_checksevertime] 用户本机时间戳不对")
                    if err == 126:
                        raise RuntimeError(f"版权原因，该地域不允许播放：{msg}")
                    raise RuntimeError(f"获取播放信息错误: code={err}, msg={msg}")

                play_info = play_data["data"]
                if play_info.get("rtmp_cdn", "").startswith("scdn"):
                    cdns = play_info.get("cdnsWithName") or []
                    if cdns:
                        req_query["cdn"] = cdns[-1]["cdn"]
                        continue
                return play_info
            except (httpx.RequestError, RuntimeError, ValueError):
                if _ == 1:
                    raise
                continue

        raise RuntimeError("获取播放信息失败")

    @staticmethod
    async def get_stream_url(
        room_id: Union[str, int],
        rate: int = 0,
        cdn: Optional[str] = None,
        protocol: str = "flv",
    ) -> str:
        play_info = await DouyuLiveChecker.get_play_info(room_id=room_id, rate=rate, cdn=cdn)

        stream_url = f"{play_info['rtmp_url']}/{play_info['rtmp_live']}"
        if protocol == "m3u8":
            return stream_url.replace(".flv", ".m3u8")
        return stream_url


class DouyuUtils:
    WhiteEncryptKey: dict[str, Any] = {}
    VipRoom: set[str] = set()
    UserAgent: str = ""
    _lock: asyncio.Lock = asyncio.Lock()
    _update_key_event: Optional[asyncio.Event] = None

    @staticmethod
    def is_key_valid(sign_type: str = "stream") -> bool:
        if not DouyuUtils.WhiteEncryptKey:
            return False
        if sign_type == "stream":
            expire_at = DouyuUtils.WhiteEncryptKey.get("expire_at", 0)
        else:
            expire_at = DouyuUtils.WhiteEncryptKey.get("cpp", {}).get("expire_at", 0)
        return expire_at > int(time.time())

    @staticmethod
    async def update_key(
        domain: str = DOUYU_WEB_DOMAIN,
        did: str = DOUYU_DEFAULT_DID,
    ) -> bool:
        async with DouyuUtils._lock:
            if DouyuUtils._update_key_event is not None:
                evt = DouyuUtils._update_key_event
                leader = False
            else:
                DouyuUtils._update_key_event = asyncio.Event()
                evt = DouyuUtils._update_key_event
                leader = True

        if not leader:
            await evt.wait()
            return DouyuUtils.is_key_valid()

        try:
            DouyuUtils.UserAgent = random_user_agent()
            rsp = await client.get(
                f"https://{domain}/wgapi/livenc/liveweb/websec/getEncryption",
                params={"did": did},
                headers={"User-Agent": DouyuUtils.UserAgent},
            )
            rsp.raise_for_status()
            data = json_loads(rsp.text)
            if data["error"] != 0:
                raise RuntimeError(f'getEncryption error: code={data["error"]}, msg={data["msg"]}')
            data["data"]["cpp"]["expire_at"] = int(time.time()) + 86400

            async with DouyuUtils._lock:
                DouyuUtils.WhiteEncryptKey = data["data"]
            return True
        except Exception:
            logger.exception("获取斗鱼加密密钥失败")
            return False
        finally:
            async with DouyuUtils._lock:
                if DouyuUtils._update_key_event is not None:
                    DouyuUtils._update_key_event.set()
                    DouyuUtils._update_key_event = None

    @staticmethod
    async def sign(
        sign_type: str,
        ts: int,
        did: str,
        rid: Union[str, int],
    ) -> dict[str, Any]:
        if not rid:
            raise ValueError("rid is None")
        if not sign_type:
            sign_type = "stream"
        if not ts:
            ts = int(time.time())
        if not did:
            did = DOUYU_DEFAULT_DID

        for _ in range(2):
            if DouyuUtils.is_key_valid(sign_type) or await DouyuUtils.update_key():
                break
        else:
            raise RuntimeError("获取加密密钥失败")

        rand_str = DouyuUtils.WhiteEncryptKey["rand_str"]
        enc_time = DouyuUtils.WhiteEncryptKey["enc_time"]
        key_data = {k: v for k, v in DouyuUtils.WhiteEncryptKey.items() if k != "cpp"}

        cpp_section_map = {"login": "danmu", "heartbeat": "heartbeat"}

        if sign_type == "stream":
            salt = "" if DouyuUtils.WhiteEncryptKey["is_special"] == 1 else f"{rid}{ts}"
            key = DouyuUtils.WhiteEncryptKey["key"]
            key_ver = ""
        elif cpp_section_map.get(sign_type):
            cpp = DouyuUtils.WhiteEncryptKey["cpp"][cpp_section_map[sign_type]]
            salt = f"{rid}{did}{ts}"
            key = cpp["key"]
            key_ver = cpp["key_ver"]
        else:
            raise ValueError(f"wrong sign type: {sign_type}")

        secret = rand_str
        for _ in range(enc_time):
            secret = hashlib.md5(f"{secret}{key}".encode("utf-8")).hexdigest()
        auth = hashlib.md5(f"{secret}{key}{salt}".encode("utf-8")).hexdigest()

        return {
            "key": key_data,
            "alg_ver": "1.0",
            "key_ver": key_ver,
            "auth": auth,
            "ts": ts,
        }
