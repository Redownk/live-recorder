import logging

from requests.utils import DEFAULT_ACCEPT_ENCODING
import random
import re
from typing import Optional
from app.core.config import local_config
from app.services.platforms.live_checkers import random_user_agent,match1,json_loads
import requests
from urllib.parse import unquote, urlparse, parse_qs, urlencode, urlunparse
from app.services.platforms.common.abogus import ABogus
from app.services.platforms.common.util import client

class DouyinLiveChecker:
    fake_headers = {
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'accept-encoding': DEFAULT_ACCEPT_ENCODING,
        'accept-language': 'zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3',
        'user-agent': random_user_agent(),
        'cookie': ""
    }

    @staticmethod
    def build_fake_headers() -> dict:
        fake_headers = DouyinLiveChecker.fake_headers
        douyin_config = local_config.get("platforms", {}).get("douyin", {})
        fake_headers['user-agent'] = DouyinUtils.DOUYIN_USER_AGENT
        fake_headers['referer'] = "https://live.douyin.com/"
        fake_headers['cookie'] = douyin_config.get("cookie", "") or ""

        if fake_headers['cookie'] != "" and not fake_headers['cookie'].endswith(';'):
            fake_headers['cookie'] += ";"
        if "ttwid" not in fake_headers['cookie']:
            fake_headers['cookie'] += f'ttwid={DouyinUtils.get_ttwid()};'
        if 'odin_ttid=' not in fake_headers['cookie']:
            fake_headers['cookie'] += f"odin_ttid={DouyinUtils.generate_odin_ttid()};"
        if '__ac_nonce=' not in fake_headers['cookie']:
            fake_headers['cookie'] += f"__ac_nonce={DouyinUtils.generate_nonce()};"
        return DouyinLiveChecker.fake_headers

    @staticmethod
    async def parse_user_unique_id(url: str, headers: dict) -> Optional[str]:
        """
        从抖音用户页提取 uniqueId（抖音号）。
        """
        response = await client.get(url, headers=headers)
        match = re.search(r'\\"uniqueId\\":\\"(.*?)\\"', response.text)
        if match and match.group(1):
            return match.group(1)
        return None


    @staticmethod
    async def get_user_info(url: str):
        logger=logging.getLogger("DouyinLiveChecker")
        se__sec_uid=None
        se__room_id=None
        se__web_rid=None
        se__room_title=None
        se__owner=None
        se__avatar=None
        fake_headers = DouyinLiveChecker.build_fake_headers()


        if 'v.douyin' in url:
            try:
                resp = await client.get(url, headers=fake_headers, follow_redirects=False)
            except:
                return False
            try:
                if resp.status_code not in {301, 302}:
                    raise
                next_url = str(resp.next_request.url)
                if "webcast.amemv" in next_url:
                    se__sec_uid = match1(next_url, r"sec_user_id=(.*?)&")
                    se__room_id = match1(next_url.split("?")[0], r"(\d+)")
                elif "isedouyin.com/share/user" in next_url:
                    se__sec_uid = match1(next_url, r"sec_uid=(.*?)&")
                else:
                    raise
            except:
                logger.error("不支持的链接")
                return False
        elif "/user/" in url:
            user_path = url.split("user/")[1].split("?")[0].strip("/")
            if len(user_path) in {55, 76}:
                se__sec_uid = user_path
                try:
                    se__web_rid = await DouyinLiveChecker.parse_user_unique_id(url, fake_headers)
                except:
                    logger.exception(f"房间号获取失败")
        else:
            web_rid = url.split('douyin.com/')[1].split('/')[0].split('?')[0]
            if web_rid[0] == "+":
                web_rid = web_rid[1:]
            se__web_rid = web_rid

        try:
            _room_info = {}
            if se__web_rid:
                _room_info = await DouyinLiveChecker.get_web_room_info(se__web_rid)
                if _room_info:
                    if not _room_info['data'].get('user'):
                        if _room_info['data'].get('prompts', '') == '直播已结束':
                            return False
                        # 可能是用户被封禁
                        raise Exception(f"{str(_room_info)}")
                    se__sec_uid = _room_info['data']['user']['sec_uid']
                    se__owner = _room_info['data']['user']['nickname']
                    se__avatar = _room_info['data']['user']['avatar_thumb']['url_list'][0]
                    # PCWeb 端无流 或 没有提供 web_rid
                if not _room_info.get('data', {}).get('data'):
                    _room_info = await DouyinLiveChecker.get_h5_room_info(se__sec_uid, se__room_id)
                    if _room_info['data'].get('room', {}).get('owner'):
                        se__web_rid = _room_info['data']['room']['owner']['web_rid']
                try:
                    # 出现异常不用提示，直接到 移动网页 端获取
                    room_info = _room_info['data']['data'][0]
                except (KeyError, IndexError):
                    # 如果 移动网页 端也没有数据，当做未开播处理
                    room_info = _room_info['data'].get('room', {})
                    # 当做未开播处理
                    # if not room_info:
                    #     logger.info(f"{self.plugin_msg}: 获取直播间信息失败 {_room_info}")
                if room_info.get('status') != 2:
                    logger.debug("未开播")
                se__room_id = room_info['id_str']
                se__room_title = room_info['title']


        except:
            logger.exception(f": 获取直播间信息失败")
            # return False
            return {
                "platform": "DOUYIN",
                "available": False,
                "result": "error",
            }

        # return {
        #     "web_rid": se__web_rid,
        #     "sec_uid": se__sec_uid,
        #     "room_id": se__room_id,
        #     "room_title": se__room_title,
        #     "owner": se__owner
        # }
        return {
            "platform":"DOUYIN",
            "roomId":se__web_rid,
            "secUid":se__sec_uid,
            "owner":se__owner,
            "avatar":se__avatar,
            "result":"success"
        }


    @staticmethod
    async def get_web_room_info(web_rid: str) -> dict:
        logger = logging.getLogger("DouyinLiveChecker")
        fake_headers = DouyinLiveChecker.build_fake_headers()

        query = {
            'app_name': 'douyin_web',
            # 'enter_from': random.choice(['link_share', 'web_live']),
            'enter_from': 'web_live',
            'live_id': '1',
            'web_rid': web_rid,
            'is_need_double_stream': "false"
        }
        target_url = DouyinUtils.build_request_url(f"https://live.douyin.com/webcast/room/web/enter/", query)
        logger.debug(f" get_web_room_info {target_url}")
        web_info = await client.get(target_url, headers=fake_headers)
        web_info = json_loads(web_info.text)
        logger.debug(f" get_web_room_info {web_info}")
        return web_info

    @staticmethod
    async def get_h5_room_info(sec_user_id: str, room_id: str) -> dict:
        '''
               Mobile web 的 API 信息，海外可能不允许使用
               '''
        if not sec_user_id:
            raise ValueError("sec_user_id is None")
        query = {
            'type_id': 0,
            'live_id': 1,
            'version_code': '99.99.99',
            'app_id': 1128,
            'room_id': room_id if room_id else 2,  # 必要但不校验
            'sec_user_id': sec_user_id
        }
        abogus = ABogus(user_agent=DouyinUtils.DOUYIN_USER_AGENT)
        query_str, _, _, _ = abogus.generate_abogus(params=urlencode(query, doseq=True), body="")
        # target_url = DouyinUtils.build_request_url(f"https://live.douyin.com/webcast/room/web/enter/", query)
        info = await client.get(
            f"https://webcast.amemv.com/webcast/room/reflow/info/?{query_str}",
            headers=DouyinLiveChecker.build_fake_headers()
        )
        info = json_loads(info.text)
        # logger.debug(f": get_h5_room_info {info}")
        return info



class DouyinUtils:
    # 抖音ttwid
    _douyin_ttwid: Optional[str] = None
    # DOUYIN_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.159 Safari/537.36'
    DOUYIN_USER_AGENT = random_user_agent()
    DOUYIN_HTTP_HEADERS = {
        'user-agent': DOUYIN_USER_AGENT
    }
    CHARSET = "abcdef0123456789"
    LONG_CHATSET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"

    @staticmethod
    def get_ttwid() -> Optional[str]:
            if not DouyinUtils._douyin_ttwid:
                page = requests.get("https://live.douyin.com/1-2-3-4-5-6-7-8-9-0", timeout=15)
                DouyinUtils._douyin_ttwid = page.cookies.get("ttwid")
            return DouyinUtils._douyin_ttwid


    @staticmethod
    def generate_ms_token() -> str:
        '''生成随机 msToken'''
        return ''.join(random.choice(DouyinUtils.LONG_CHATSET) for _ in range(184))


    @staticmethod
    def generate_nonce() -> str:
        """生成 21 位随机十六进制小写 nonce"""
        return ''.join(random.choice(DouyinUtils.CHARSET) for _ in range(21))


    @staticmethod
    def generate_odin_ttid() -> str:
        """生成 160 位随机十六进制小写 odin_ttid"""
        return ''.join(random.choice(DouyinUtils.CHARSET) for _ in range(160))


    @staticmethod
    def build_request_url(url: str, query: Optional[dict] = None) -> str:
        # NOTE: 不能在类级别初始化，否则非首次生成的 abogus 有问题，原因未知
        abogus = ABogus(user_agent=DouyinUtils.DOUYIN_USER_AGENT)
        parsed_url = urlparse(url)
        existing_params = query or parse_qs(parsed_url.query)
        existing_params['aid'] = ['6383']
        existing_params['compress'] = ['gzip']
        existing_params['device_platform'] = ['web']
        existing_params['browser_language'] = ['zh-CN']
        existing_params['browser_platform'] = ['Win32']
        existing_params['browser_name'] = [DouyinUtils.DOUYIN_USER_AGENT.split('/')[0]]
        existing_params['browser_version'] = [DouyinUtils.DOUYIN_USER_AGENT.split(existing_params['browser_name'][0])[-1][1:]]
        if 'msToken' not in existing_params:
            existing_params['msToken'] = [DouyinUtils.generate_ms_token()]
        new_query_string = urlencode(existing_params, doseq=True)
        signed_query_string, _, _, _ = abogus.generate_abogus(params=new_query_string, body="")
        new_url = urlunparse((
            parsed_url.scheme,
            parsed_url.netloc,
            parsed_url.path,
            parsed_url.params,
            signed_query_string,
            parsed_url.fragment
        ))
        return new_url
