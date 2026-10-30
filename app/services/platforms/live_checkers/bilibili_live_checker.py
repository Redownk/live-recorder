
import time
import logging
from requests.utils import DEFAULT_ACCEPT_ENCODING
from app.core.config import local_config
from app.services.platforms.common.util import client
from app.services.platforms.live_checkers import random_user_agent,match1,json_loads,wbi
import json
from app.modules.recording.quality import quality_index

class BiliLiveChecker:
    fake_headers = {
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'accept-encoding': DEFAULT_ACCEPT_ENCODING,
        'accept-language': 'zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3',
        'user-agent': random_user_agent(),
        "cookie":""
    }

    @staticmethod
    def build_fake_headers() -> dict:
        fake_headers = BiliLiveChecker.fake_headers
        bilibili_config = local_config.get("platforms", {}).get("bilibili", {})
        fake_headers["cookie"] = bilibili_config.get("cookie", "") or ""

        return fake_headers


    @staticmethod
    async def get_user_info(url: str, cookie: str = None):
        """
        拆解逻辑：对应 douyin_live_checker 的 get_user_info
        获取房间ID、标题、主播UID等基础信息
        """
        # headers = {
        #     'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        #     'accept-encoding': DEFAULT_ACCEPT_ENCODING,
        #     'accept-language': 'zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3',
        #     'user-agent': random_user_agent(),
        #     'Referer': url
        # }
        # if cookie:
        #     headers['cookie'] = cookie

        # 1. 处理短链接跳转
        if "b23.tv" in url:
            resp = await client.get(url, follow_redirects=False)
            url = str(resp.next_request.url)

        room_id = match1(url, r'bilibili.com/(\d+)')

        # # 2. 更新 WBI 签名
        # if int(time.time()) - wbi.last_update >= wbi.UPDATE_INTERVAL:
        #     await BiliLiveChecker.update_wbi_context(headers)

        # 3. 请求房间基础信息
        # params = {"room_id": room_id, "web_location": BiliUtils.WBI_WEB_LOCATION}
        # wbi.sign(params)

        # resp = await client.get(f"{BiliUtils.OFFICIAL_API}/xlive/web-room/v1/index/getInfoByRoom",
        #                         params=params, headers=headers)
        # data = resp.json()
        data=await BiliLiveChecker.get_room_info(room_id)
        is_live=True
        # if data['code'] != 0 or data['data']['room_info']['live_status'] != 1:
            # return None  # 未开播或错误
            # is_live=False
        if data['code'] != 0:
            return {
                "platform": "BILIBILI",
                "available":False,
                "result":"error",
            }
        room_info = data['data']['room_info']
        # return {
        #     "is_live": is_live,
        #     "room_id": room_info['room_id'],
        #     "title": room_info['title'],
        #     "uid": room_info['uid'],
        #     "cover": room_info['cover'],
        #     "live_start_time": room_info['live_start_time'],
        #     "special_type": room_info['special_type']
        # }
        return {
            "platform":"BILIBILI",
            "roomId": room_info['room_id'],
            'secUid': room_info['uid'],
            "owner": data['data']['anchor_info']['base_info']['uname'],
            "avatar": data['data']['anchor_info']['base_info']['face'],
            "result":"success"
        }

    @staticmethod
    async def get_room_info(room_id: str) -> dict:
        headers=BiliLiveChecker.build_fake_headers()

        # 2. 更新 WBI 签名
        if int(time.time()) - wbi.last_update >= wbi.UPDATE_INTERVAL:
            await BiliLiveChecker.update_wbi_context(headers)
        params = {"room_id": room_id, "web_location": BiliUtils.WBI_WEB_LOCATION}
        wbi.sign(params)
        resp = await client.get(f"{BiliUtils.OFFICIAL_API}/xlive/web-room/v1/index/getInfoByRoom",
                                params=params, headers=headers)
        data = resp.json()
        return data

    @staticmethod
    async def get_play_api_data(room_id: int, qn: int) -> dict:
        """
        拆解逻辑：对应 get_web_room_info
        获取直播接口的原始 JSON 数据
        """
        headers=BiliLiveChecker.build_fake_headers()
        params = {
            'room_id': str(room_id),
            'qn': str(qn),
            'platform': 'html5',
            'protocol': '0,1',
            'format': '0,1,2',
            'codec': '0',
            'web_location': BiliUtils.WBI_WEB_LOCATION,
        }
        # 2. 更新 WBI 签名
        if int(time.time()) - wbi.last_update >= wbi.UPDATE_INTERVAL:
            await BiliLiveChecker.update_wbi_context(headers)
        wbi.sign(params)
        url = f"{BiliUtils.OFFICIAL_API}/xlive/web-room/v2/index/getRoomPlayInfo"
        resp = await client.get(url, params=params, headers=headers)
        return resp.json().get('data')

    @staticmethod
    async def get_stream_url(room_id: int, qn: int, protocol: str, quality: str = "best") -> str:
        """
        拆解逻辑：对应获取直播流方法
        从 API 数据中解析出最终可用的播放地址
        """

        play_info = await BiliLiveChecker.get_play_api_data(room_id, qn)
        if not play_info or not play_info.get('playurl_info'):
            return None

        if quality != "best":
            advertised = set()
            for stream in play_info['playurl_info']['playurl']['stream']:
                for fmt in stream.get('format', []):
                    for codec in fmt.get('codec', []):
                        advertised.update(value for value in codec.get('accept_qn', []) if isinstance(value, int))
            qualities = sorted(advertised, reverse=True)
            if qualities:
                selected = qualities[quality_index(len(qualities), quality)]
                selected_info = await BiliLiveChecker.get_play_api_data(room_id, selected)
                if selected_info and selected_info.get('playurl_info'):
                    play_info = selected_info
            else:
                logging.getLogger(__name__).warning("平台未提供清晰度列表，使用当前可用直播流")

        streams = play_info['playurl_info']['playurl']['stream']

        # 默认解析第一个流 (FLV 或 HLS)
        # 对应原逻辑中 aget_stream 的选择逻辑
        if protocol == 'hls_fmp4' and len(streams) > 1:
            codec_data = streams[1]['format'][0]['codec'][0]
        else:
            codec_data = streams[0]['format'][0]['codec'][0]

        stream_data = BiliUtils.parse_stream_url(codec_data)

        # 提取第一个可用的 CDN 地址
        qn_key = list(stream_data.keys())[0]
        cdn_key = list(stream_data[qn_key].keys())[0]
        info = stream_data[qn_key][cdn_key]['url']

        return f"{info['host']}{info['base_url']}{info['extra']}"

    @staticmethod
    async def update_wbi_context(headers: dict):
        """辅助方法：更新 WBI 密钥"""
        resp = await client.get('https://api.bilibili.com/x/web-interface/nav', headers=headers)
        data = resp.json().get('data', {})
        wbi_img = data.get('wbi_img', {})
        img_url = wbi_img.get('img_url')
        sub_url = wbi_img.get('sub_url')
        if img_url and sub_url:
            img_key = img_url.split('/')[-1].split('.')[0]
            sub_key = sub_url.split('/')[-1].split('.')[0]
            wbi.update_key(img_key, sub_key)

    @staticmethod
    async def get_online_info(sec_uid:str ,room_id: int):
        headers=BiliLiveChecker.build_fake_headers()
        params = {
            "ruid": str(sec_uid),
            "room_id": str(room_id),
            "page": "1",
            "page_size": "1",
            "type": "online_rank",
            "switch":"contribution_rank",
            "platform": "web",
            "webLocation": BiliUtils.WBI_WEB_LOCATION
        }
        # 2. 更新 WBI 签名
        if int(time.time()) - wbi.last_update >= wbi.UPDATE_INTERVAL:
            await BiliLiveChecker.update_wbi_context(headers)
        wbi.sign(params)
        url = f"{BiliUtils.OFFICIAL_API}/xlive/general-interface/v1/rank/queryContributionRank"
        resp = await client.get(url, params=params, headers=headers)
        return resp.json().get('data')

class BiliUtils:
    OFFICIAL_API = "https://api.live.bilibili.com"
    WBI_WEB_LOCATION = "444.8"
    STREAM_NAME_REGEXP = r"/live-bvc/\d+/(live_[^/\.]+)"

    @staticmethod
    def get_cookies_from_file(file_path: str) -> str:
        try:
            with open(file_path, encoding='utf-8') as f:
                cookies = json.load(f)["cookie_info"]["cookies"]
                return ''.join([f"{i['name']}={i['value']};" for i in cookies])
        except Exception:
            return ""

    @staticmethod
    def parse_stream_url(data) -> dict:
        suffix_regexp = r'suffix=([^&]+)'
        if isinstance(data, str):
            host = "https://" + match1(data, r'https?://([^/]+)')
            return {
                'url': {'host': host, 'base_url': data.split("?")[0].split(host)[1] + "?", 'extra': data.split("?")[1]},
                'stream_name': match1(data, BiliUtils.STREAM_NAME_REGEXP),
                'suffix': match1(data, suffix_regexp)
            }
        elif isinstance(data, dict):
            streams = {}
            qn = data['current_qn']
            streams.setdefault(qn, {})
            for info in data['url_info']:
                cdn = match1(info['extra'], r'cdn=([^&]+)')
                streams[qn][cdn] = {
                    'url': {'host': info['host'], 'base_url': data['base_url'], 'extra': info['extra']},
                    'stream_name': match1(data['base_url'], BiliUtils.STREAM_NAME_REGEXP),
                    'suffix': match1(info['extra'], suffix_regexp)
                }
            return streams
