import asyncio

from app.services.platforms.live_checkers import douyu_live_checker
from app.services.platforms.live_checkers.douyin_live_checker import DouyinLiveChecker
from app.services.platforms.live_checkers.bilibili_live_checker import BiliLiveChecker
from app.services.platforms.live_checkers.douyu_live_checker import DouyuLiveChecker

config = {
    "user":{
        "douyin_cookie":"__ac_nonce=0689304fa00711c357c2e;__ac_signature=_02B4Z6wo00f011TLmJwAAIDBtwRoCWV4DLNU65wAAL2tcd;sessionid=2dfe95d65acb4da60653bd6028077fb7;",
    }
}

async def main():
    # url = "https://live.douyin.com/Y709455"
    # checker = DouyinLiveChecker(url)
    #
    # web_rid = "127453393722"   # 直接测试房间号
    # result = await checker.get_web_room_info(web_rid)
    #
    # print(result)
    # url = "https://live.douyin.com/127453393722"
    # info = await DouyinLiveChecker().get_web_room_info('73355700802')
    # print(checker)
    # await checker.acheck_stream()
    # print(checker)
    # info=await DouyinLiveChecker.get_web_room_info(web_rid)
    # print(info)
    # cookie="SESSDATA=404bb913%2C1788022393%2C3ac83231CjCFwSN1mozhxd1qjjzZXKMA6Tm3eWKwxmfIrngxAzQaErbzKmQDa7zAOef9OzoyOwoSVnBiNVoyMUwxZDl0V3J1WVJiWWw2OHVqWmEyUWE5bmRfRmFrVlVYS19MZ3FJMEo5dEh6VGZHcTBuNkFiNURRQUpDSXVkVkRGTDdOdElNeGp5TWVBWGx3IIEC; bili_jct=e4793e68c3ceae3e76dd0a151cdd2abb; DedeUserID=3546734825311155; DedeUserID__ckMd5=dedf4e69ae7c19b7; sid=g1xuzrpg; buvid3=C039C4F8-92C9-FE5E-01E0-F38DFABD607909354infoc"
    # url="https://live.bilibili.com/21574974"
    # info =await BiliLiveChecker.get_user_info(url)
    # info = await BiliLiveChecker.get_play_api_data('578815','25000')
    # info =await BiliLiveChecker.get_stream_url('578815','25000','hls_fmp4')
    # info = await BiliLiveChecker.get_room_info('578815')
    # print(info['data']['data'][0]['room_view_stats']['display_value'])
    # info =await BiliLiveChecker.get_online_info("1","1788061058")
    # print(info)
    # info = await DouyuLiveChecker.get_user_info("https://www.douyu.com/8554124")
    # info = await DouyuLiveChecker.get_room_info("12543769")
    # info = await DouyuLiveChecker.get_stream_url("12543769")
    info = await DouyinLiveChecker.get_user_info("https://www.douyin.com/user/MS4wLjABAAAAVBI-jfyOLy98IrXwNxk5kOFkH-NLn-liSzSVFZCRPXk")
    print(info)

if __name__ == '__main__':
    asyncio.run(main())
