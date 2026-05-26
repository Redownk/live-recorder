import logging

import requests
import time
import json
from app.services.platforms.douyin_recorder.sign import ABogus

class DouyinLiveChecker:
    ENTER_ROOM_API = "https://live.douyin.com/webcast/room/web/enter/"

    QUALITY_LIST = {
        "real_origin": "真原画",
        "origin": "原画",
        "uhd": "蓝光",
        "hd": "超清",
        "sd": "高清",
        "ld": "标清",
        "ao": "音频流"
    }

    cookie_cache = {
        "start_time": 0,
        "cookies": ""
    }


    @staticmethod
    def check(url: str) -> dict:
        try:
            web_rid = DouyinLiveChecker.extract_web_rid(url)

            info = DouyinLiveChecker.get_room_info(web_rid)
            return {
                "platform": "DOUYIN",
                "roomId":web_rid,
                "secUid":info.get("sec_uid"),
                "owner": info.get("owner"),
                "result": "success",
            }
            return info

        except Exception as e:
            return {
                "platform": "DOUYIN",
                "available": False,
                "result": "error",
            }

    @staticmethod
    def extract_web_rid(url: str) -> str:
        """
        从抖音直播链接提取 web_rid
        例如：
        https://live.douyin.com/123456789
        """
        return url.rstrip("/").split("/")[-1]

    @staticmethod
    def get_cookie():
        """获取 cookie（缓存 6 小时）"""
        now = time.time()
        if DouyinLiveChecker.cookie_cache["start_time"] and now - DouyinLiveChecker.cookie_cache["start_time"] < 6 * 60 * 60:
            return DouyinLiveChecker.cookie_cache["cookies"]

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/119.0.0.0 Safari/537.36"
        }
        resp = requests.get("https://live.douyin.com/", headers=headers)
        if "set-cookie" not in resp.headers and "Set-Cookie" not in resp.headers:
            raise Exception("获取 Cookie 失败")

        set_cookie = resp.headers.get("set-cookie") or resp.headers.get("Set-Cookie")
        cookies = []
        for c in set_cookie.split(","):
            cookies.append(c.split(";")[0])
        cookie_str = "; ".join(cookies)

        DouyinLiveChecker.cookie_cache["start_time"] = now
        DouyinLiveChecker.cookie_cache["cookies"] = cookie_str
        return cookie_str

    @staticmethod
    def get_room_info(web_rid):
        """获取直播间信息"""
        cookies = DouyinLiveChecker.get_cookie()

        # ===== 构造参数字符串（必须顺序一致）=====
        params_str = (
            f"aid=6383&live_id=1&device_platform=web&language=zh-CN"
            f"&enter_from=web_live&cookie_enabled=true"
            f"&screen_width=1920&screen_height=1080"
            f"&browser_language=zh-CN&browser_platform=MacIntel"
            f"&browser_name=Chrome&browser_version=108.0.0.0"
            f"&web_rid={web_rid}&Room-Enter-User-Login-Ab=0"
            f"&is_need_double_stream=false"
        )
        body = ""

        # ===== 生成 a_bogus =====
        ab = ABogus()
        final_params, a_bogus, ua, fp = ab.generate_abogus(params_str, body)

        headers = {
            "cookie": cookies,
            "User-Agent": ua,
            "Referer": "https://live.douyin.com/",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }

        resp = requests.get(DouyinLiveChecker.ENTER_ROOM_API, params=final_params, headers=headers)
        data = resp.json()

        if data["status_code"] != 0:
            raise Exception(f"API 请求失败: {data}")

        room_data = data["data"]["data"][0]
        user_data = data["data"]["user"]


        if not room_data.get("stream_url"):
            return {
                "living": False,
                "owner": user_data["nickname"],
                "title": room_data.get("title", user_data["nickname"]),
                "sec_uid": user_data["sec_uid"],
                "streams": {}
            }

        pull_data = room_data["stream_url"]["live_core_sdk_data"]["pull_data"]
        qualities = pull_data["options"]["qualities"]
        stream_data = json.loads(pull_data["stream_data"])["data"]

        streams = {}
        for q in qualities:
            key = q["sdk_key"]
            desc = q["name"]
            flv = stream_data.get(key, {}).get("main", {}).get("flv")
            hls = stream_data.get(key, {}).get("main", {}).get("hls")
            streams[key] = {
                "desc": desc,
                "flv": flv,
                "hls": hls
            }

        if "ao" in streams:
            real_origin_flv = streams["ao"]["flv"].replace("&only_audio=1", "")
            real_origin_hls = streams["ao"]["hls"].replace("&only_audio=1", "")
            streams["real_origin"] = {
                "desc": DouyinLiveChecker.QUALITY_LIST["real_origin"],
                "flv": real_origin_flv,
                "hls": real_origin_hls
            }

        # return {
        #     "living": data["data"]["room_status"] == 0,
        #     "owner": user_data["nickname"],
        #     "title": room_data["title"],
        #     "avatar": user_data["avatar_thumb"]["url_list"][0],
        #     "cover": room_data["cover"]["url_list"][0],
        #     "streams": streams
        # }

        return {
            "owner": user_data["nickname"],
            "sec_uid" : user_data["sec_uid"],
        }
        # return resp.request.url