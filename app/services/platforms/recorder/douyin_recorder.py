import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
from sqlalchemy import text

from app.core.logger import get_logger
from app.services.platforms.live_checkers.douyin_live_checker import DouyinLiveChecker
from app.services.platforms.recorder.base_recorder import BaseRecorder
from app.services.platforms.recorder import get_ffmpeg_path
from app.core.session import get_db_session


logger = get_logger(__name__)


class DouyinRecorder(BaseRecorder):
    RECORD_DIR = Path(__file__).resolve().parents[4] / "record"

    QUALITY_LIST = {
        "real_origin": "真原画",
        "origin": "原画",
        "uhd": "蓝光",
        "hd": "超清",
        "sd": "高清",
        "ld": "标清",
        "ao": "音频流"
    }

    #检测直播间状态
    async def check_live_status(self):
        info = await DouyinLiveChecker.get_web_room_info(self.room_id)
        data = info.get("data") or {}
        room_list = data.get("data") or []
        user_data = data.get("user") or {}

        if not user_data:
            if data.get('prompts', '') == '直播已结束':
                return {
                    "is_live": False,
                }
            return {
                "is_live": False,
            }

        if not room_list:
            return {
                "is_live": False,
                "owner": user_data.get("nickname", ""),
                "title": user_data.get("nickname", ""),
                "streams": {}
            }

        room_data = room_list[0]

        if not room_data.get("stream_url"):
            return {
                "is_live": False,
                "owner": user_data.get("nickname", ""),
                "title": room_data.get("title", user_data.get("nickname", "")),
                "streams": {}
            }

        pull_data = (
            room_data.get("stream_url", {})
            .get("live_core_sdk_data", {})
            .get("pull_data", {})
        )
        qualities = pull_data.get("options", {}).get("qualities") or []
        stream_data = json.loads(pull_data.get("stream_data", "{}")).get("data", {})

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

        # 真原画处理
        if "ao" in streams:
            real_origin_flv = (streams["ao"]["flv"] or "").replace("&only_audio=1", "")
            real_origin_hls = (streams["ao"]["hls"] or "").replace("&only_audio=1", "")
            streams["real_origin"] = {
                "desc": DouyinRecorder.QUALITY_LIST["real_origin"],
                "flv": real_origin_flv,
                "hls": real_origin_hls
            }

        return {
            "is_live": data.get("room_status") == 0,
            "owner": user_data.get("nickname", ""),
            "title": room_data.get("title", user_data.get("nickname", "")),
            "avatar": ((user_data.get("avatar_thumb") or {}).get("url_list") or [""])[0],
            "cover": ((room_data.get("cover") or {}).get("url_list") or [""])[0],
            "streams": streams
        }

    #启动录制
    async def record(self, live_info):

        start_time = datetime.now()
        file_name = f"{self.platform}_{live_info['owner']}_{start_time.strftime('%Y%m%d%H%M%S')}"
        self.RECORD_DIR.mkdir(parents=True, exist_ok=True)
        output_prefix = str(self.RECORD_DIR / file_name)

        priority = ["real_origin", "origin", "uhd", "hd", "sd", "ld", "ao"]

        selected_q = None
        for q in priority:
            if q in live_info["streams"]:
                selected_q = q
                break

        if not selected_q:
            logger.warning(self._log_message("没有可用清晰度"))
            return

        stream = live_info["streams"][selected_q]
        stream_url = stream["hls"] or stream["flv"]

        # 写入数据库日志
        async with get_db_session(self.app) as db:
            result = await db.execute(text("""
                INSERT INTO live_room_log
                    (live_room_id, platform, owner, title, start_live, create_time, del_flag)
                VALUES (:live_room_id, :platform, :owner, :title, :start_live, CURRENT_TIMESTAMP, 0)
            """), {
                "live_room_id": self.room["id"],
                "platform": self.platform,
                "owner": live_info["owner"],
                "title": live_info["title"],
                "start_live": start_time
            })
            await db.execute(text("""
                                  UPDATE live_room
                                  SET last_live_time=:last_live_time
                                  where id = :live_room_id
                                  """), {
                                 "live_room_id": self.room["id"],
                                 "last_live_time": start_time
                             })
            await db.commit()
            log_id = result.lastrowid

        # 启动异步录制任务
        asyncio.create_task(
            self.record_loop(log_id, output_prefix, stream_url)
        )

    #异步录制任务
    async def record_loop(self, log_id, file_name, stream_url):
        headers = (
            "Referer: https://live.douyin.com/\r\n"
            "Origin: https://live.douyin.com\r\n"
            "User-Agent: Mozilla/5.0\r\n"
        )
        ffmpeg_path = get_ffmpeg_path()
        is_m3u8 = ".m3u8" in stream_url.lower()
        reconnect_count = 0
        max_reconnect = 10
        segment_index = 1
        logger.info(self._log_message("开始录制: %s"), file_name)
        start_timestamp = time.time()
        process = None
        stop_event = asyncio.Event()
        # 后台锁续期任务
        renew_task = asyncio.create_task(self._renew_lock_loop(stop_event))
        data_task = asyncio.create_task(self._collect_live_data_loop(log_id))
        try:
            while reconnect_count < max_reconnect:
                if is_m3u8:
                    output_file = f"{file_name}_{segment_index}.ts"
                    cmd = [
                        ffmpeg_path,
                        "-headers", headers,
                        "-i", stream_url,
                        "-c", "copy",
                        "-f", "mpegts",
                        output_file
                    ]
                else:
                    output_file = f"{file_name}_{segment_index}.flv"
                    cmd = [
                        ffmpeg_path,
                        "-headers", headers,
                        "-i", stream_url,
                        "-c", "copy",
                        "-f", "flv",
                        output_file
                    ]
                try:
                    process = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL
                    )
                    logger.info(self._log_message("ffmpeg 启动"))
                    return_code = await process.wait()
                    logger.info(self._log_message("流断开，return_code: %s"), return_code)
                    # ⭐ 判断文件是否真正生成且有内容
                    import os
                    if os.path.exists(output_file) and os.path.getsize(output_file) > 1024:
                        segment_index += 1
                        reconnect_count = 0
                        logger.info(self._log_message("有效分段: %s"), output_file)
                    else:
                        # 删除无效文件
                        if os.path.exists(output_file):
                            os.remove(output_file)
                    # 下播三次确认
                    offline_confirm = 0
                    for _ in range(3):
                        await asyncio.sleep(3)
                        live_info = await self.check_live_status()
                        if not live_info.get("is_live"):
                            offline_confirm += 1
                    if offline_confirm >= 3:
                        logger.info(self._log_message("确认主播下播"))
                        break
                    # 网络断流重连
                    reconnect_count += 1
                    wait_time = min(5 * reconnect_count, 30)

                    logger.warning(self._log_message("断流，%s秒后重连 (%s/%s)"), wait_time, reconnect_count, max_reconnect)
                    await asyncio.sleep(wait_time)
                except Exception as e:
                    logger.exception(self._log_message("录制异常: %s"), e)
                    reconnect_count += 1
                    await asyncio.sleep(5)
        finally:
            renew_task.cancel()
            data_task.cancel()
            try:
                await data_task
            except asyncio.CancelledError:
                pass
            if process and process.returncode is None:
                try:
                    process.terminate()
                    logger.info(self._log_message("清理遗留 FFmpeg 进程"))
                except:
                    pass
            await self.release_record_lock()
            end_time = datetime.now()
            live_seconds = int(time.time() - start_timestamp)
            max_online_count = await self._get_max_online_count(log_id)
            last_total_user_count = await self._get_last_total_user_count(log_id)
            async with get_db_session(self.app) as db:
                await db.execute(text("""
                    UPDATE live_room_log
                    SET end_live  = :end_live,
                        live_time = :live_time,
                        user_num = :user_num,
                        total_user = :total_user
                    WHERE id = :id
                """), {
                    "end_live": end_time,
                    "live_time": live_seconds,
                    "user_num": max_online_count,
                    "total_user": last_total_user_count,
                    "id": log_id
                })
                await db.commit()

            logger.info(self._log_message("%s 直播结束"), file_name)
            await self._post_process(file_name, segment_index,log_id)

    async def _renew_lock_loop(self,stop_event: asyncio.Event):
        try:
            while True:
                await asyncio.sleep(30)
                success=await self.renew_record_lock()
                if not success:
                    stop_event.set()
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception(self._log_message("续锁任务发生异常: %s"), e)
            stop_event.set()

    # ==========================
    # 📊 直播数据采集任务
    # ==========================
    async def _collect_live_data_loop(self, log_id):

        try:
            while True:

                await asyncio.sleep(300)  # 每5分钟
                info = await DouyinLiveChecker.get_web_room_info(self.room_id)

                if not info.get("data"):
                    continue

                try:
                    like_count= info['data']['data'][0]['like_count']
                    online_count = info['data']['data'][0]['room_view_stats']['display_value']
                    total_user_count= info['data']['data'][0]['stats']['total_user_str']
                except (KeyError, TypeError, IndexError) as e:
                    logger.warning(self._log_message("Douyin stats missing key: %s, skipping"), e)
                    continue

                async with get_db_session(self.app) as db:
                    await db.execute(text("""
                                          INSERT INTO live_room_stats
                                              (live_room_id,live_room_log_id, online_count, like_count, watch_user_count, collect_time)
                                          VALUES (:live_room_id,:log_id, :online, :like, :watch, CURRENT_TIMESTAMP)
                                          """), {
                                         "live_room_id": self.room['id'],
                                         "log_id": log_id,
                                         "online": online_count,
                                         "like": like_count,
                                         "watch": total_user_count
                                     })

                    await db.commit()

                # print(f"数据采集: watch={watch_count} like={like_count}")

        except asyncio.CancelledError:
            logger.info(self._log_message("数据采集任务结束"))
