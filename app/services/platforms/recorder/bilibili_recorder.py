import asyncio
import time
from app.core.session import get_db_session
from app.core.logger import get_logger
from app.core.log_context import recording_log_context
from app.services.platforms.live_checkers.bilibili_live_checker import BiliLiveChecker
from app.services.platforms.recorder import get_ffmpeg_path
from app.services.platforms.recorder.base_recorder import BaseRecorder
from app.modules.recording.health import RecordingHealthError
from app.modules.recording.disk import DiskSpaceError
from datetime import datetime
from sqlalchemy import text


logger = get_logger(__name__)

class BilibiliRecorder(BaseRecorder):

    async def refresh_stream_url(self, live_info, previous_url):
        return await BiliLiveChecker.get_stream_url(self.room_id, 25000, 'hls_fmp4', quality=self.recording_options().quality)

    async def check_live_status(self):
        info =await BiliLiveChecker.get_room_info(self.room_id)


        if info["data"]["room_info"]["live_status"]!=1:
            return {
                "is_live":False
            }
        return {
            "is_live": info["data"]["room_info"]["live_status"]==1,
            "owner": info["data"]["anchor_info"]["base_info"]["uname"],
            "title": info["data"]["room_info"]["title"],
        }




    async def record(self,live_info):
        start_time= datetime.now()
        output_prefix = await self.create_output_prefix(live_info, start_time)
        stream_url = await self.refresh_stream_url(live_info, None)
        async with get_db_session(self.app) as db:
            result = await db.execute(text("""
                INSERT INTO live_room_log
                    (live_room_id, platform, owner, title, start_live, create_time, del_flag)
                VALUES (:room_id, :platform, :owner, :title, :start_live, CURRENT_TIMESTAMP, 0)
            """),{
                "room_id": self.room["id"],
                "platform": self.platform,
                "owner": live_info["owner"],
                "title": live_info["title"],
                "start_live": start_time
            })
            await db.execute(text("""
                UPDATE live_room SET last_live_time=:last_live_time
                where id=:live_room_id
            """),{
                "live_room_id": self.room["id"],
                "last_live_time": start_time
            })
            await db.commit()
            log_id = result.lastrowid
        self._log_id = log_id
        await self.record_loop(log_id,output_prefix,stream_url)

    @recording_log_context
    async def record_loop(self,log_id,file_name,stream_url):
        # headers=BiliLiveChecker.build_fake_headers()
        # 获取 headers 字典
        header_dict = BiliLiveChecker.build_fake_headers()

        # 将字典转换为 FFmpeg 所需的字符串格式
        # 格式示例: "Referer: https://live.bilibili.com\r\nUser-Agent: Mozilla/5.0..."
        headers_str = ""
        for key, value in header_dict.items():
            headers_str += f"{key}: {value}\r\n"

        ffmpeg_path=get_ffmpeg_path()

        is_m3u8 = ".m3u8" in stream_url.lower()

        reconnect_count = 0
        max_reconnect = 10
        segment_index = 1
        logger.info(self._log_message("开始录制: %s"), file_name)
        start_timestamp = time.time()
        process = None

        data_task = asyncio.create_task(self._collect_live_data_loop(log_id))
        try:
            while reconnect_count < max_reconnect:
                is_m3u8 = ".m3u8" in stream_url.lower()
                if is_m3u8:
                    output_file = f"{file_name}_{segment_index}.ts"
                    cmd = [
                        ffmpeg_path,
                        "-nostdin", "-n",
                        "-headers", headers_str,
                        "-i", stream_url,
                        "-c", "copy",
                        "-f", "mpegts",
                        output_file
                    ]
                else:
                    output_file = f"{file_name}_{segment_index}.flv"
                    cmd = [
                        ffmpeg_path,
                        "-nostdin", "-n",
                        "-headers", headers_str,
                        "-i", stream_url,
                        "-c", "copy",
                        "-f", "flv",
                        output_file
                    ]
                try:
                    process = await self.spawn_recording_process(cmd)

                    logger.info(self._log_message("ffmpeg 启动"))
                    self.recording_started(log_id)
                    try:
                        return_code = await self.wait_recording_process(process, output_file, log_id)
                    finally:
                        self.recording_reconnecting(log_id)


                    logger.info(self._log_message("流断开，return_code: %s"), return_code)

                    segment_advance = await self.complete_recording_segment(output_file, log_id)
                    segment_index += segment_advance
                    if self._segment_health_error is not None:
                        stream_url = await self.recover_recording_stream(stream_url)
                        if stream_url is None:
                            break
                        continue
                    if segment_advance and self._segment_had_data:
                        reconnect_count = 0
                        logger.info(self._log_message("有效分段: %s"), output_file)

                    # ===== 下播三次确认 =====
                    offline_confirm = 0
                    for _ in range(3):
                        await asyncio.sleep(3)
                        live_info = await self.check_live_status()
                        if not live_info.get("is_live"):
                            offline_confirm += 1

                    if offline_confirm >= 3:
                        logger.info(self._log_message("确认主播下播"))
                        break

                    # ===== 网络断流重连 =====
                    reconnect_count += 1
                    wait_time = min(5 * reconnect_count, 30)

                    logger.warning(self._log_message("断流，%s秒后重连 (%s/%s)"), wait_time, reconnect_count, max_reconnect)
                    await asyncio.sleep(wait_time)
                    stream_url = await self.refresh_stream_url(live_info, stream_url)

                except (RecordingHealthError, DiskSpaceError):
                    raise
                except Exception as e:
                    logger.exception(self._log_message("录制异常: %s"), e)
                    reconnect_count += 1
                    await asyncio.sleep(5)
        finally:
            self.recording_finished(log_id)
            data_task.cancel()
            await asyncio.gather(data_task, return_exceptions=True)
            await self.stop_process(process)

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
                        total_user = :total_user,
                        interrupted = :interrupted
                    WHERE id = :id
                """), {
                    "end_live": end_time,
                    "live_time": live_seconds,
                    "user_num": max_online_count,
                    "total_user": last_total_user_count,
                    "interrupted": bool(asyncio.current_task().cancelling()) or self._health_failed,
                    "id": log_id
                })
                await db.commit()

            logger.info(self._log_message("%s 直播结束"), file_name)
            if not asyncio.current_task().cancelling() and not self._health_failed:
                await self._post_process(file_name, segment_index,log_id)
            elif self.recording_options().segment_minutes and not self._health_failed:
                await self.register_timed_segments(file_name, segment_index, log_id, probe_durations=False)
            else:
                logger.info(self._log_message("录制已中断，保留分片文件"))

    async def _collect_live_data_loop(self, log_id):
        try:
            while True:

                await asyncio.sleep(300)
                info = await BiliLiveChecker.get_room_info(self.room_id)
                online_info= await BiliLiveChecker.get_online_info(self.room["sec_uid"],self.room_id)
                if not info.get("data"):
                    continue

                try:
                    like_count = info["data"]["like_info_v3"]["total_likes"]
                    online_count = online_info["count"]
                    total_user_count = info["data"]["watched_show"]["num"]
                except (KeyError, TypeError) as e:
                    logger.warning(self._log_message("Bilibili stats missing key: %s, skipping"), e)
                    continue

                async with get_db_session(self.app) as db:
                    await db.execute(text("""
                                          INSERT INTO live_room_stats
                                          (live_room_id, live_room_log_id, online_count, like_count, watch_user_count, collect_time)
                                          VALUES (:live_room_id, :log_id, :online, :like, :watch, CURRENT_TIMESTAMP)
                                          """), {
                                         "live_room_id": self.room['id'],
                                         "log_id": log_id,
                                         "online": online_count,
                                         "like": like_count,
                                         "watch": total_user_count
                                     })

                    await db.commit()


        except asyncio.CancelledError:
            logger.info(self._log_message("数据采集任务结束"))
