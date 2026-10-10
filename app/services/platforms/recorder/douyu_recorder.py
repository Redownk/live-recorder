import asyncio
import time
from datetime import datetime

from sqlalchemy import text

from app.core.logger import get_logger
from app.core.session import get_db_session
from app.services.platforms.live_checkers.douyu_live_checker import DouyuLiveChecker
from app.services.platforms.recorder import get_ffmpeg_path
from app.services.platforms.recorder.base_recorder import BaseRecorder


logger = get_logger(__name__)


class DouyuRecorder(BaseRecorder):

    async def check_live_status(self):
        info = await DouyuLiveChecker.get_room_info(self.room_id)
        room_info = info.get("room") or {}

        if room_info.get("show_status") != 1 or room_info.get("videoLoop") != 0:
            return {
                "is_live": False,
            }

        return {
            "is_live": True,
            "owner": room_info.get("nickname", ""),
            "title": room_info.get("room_name", "")
        }

    async def record(self, live_info):
        start_time = datetime.now()
        output_prefix = await self.create_output_prefix(live_info, start_time)

        stream_url = await DouyuLiveChecker.get_stream_url(self.room_id)

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

        asyncio.create_task(
            self.record_loop(log_id, output_prefix, stream_url)
        )

    async def record_loop(self, log_id, file_name, stream_url):
        header_dict = DouyuLiveChecker.build_fake_headers()
        headers_str = ""
        for key, value in header_dict.items():
            if value:
                headers_str += f"{key}: {value}\r\n"

        ffmpeg_path = get_ffmpeg_path()
        is_m3u8 = ".m3u8" in stream_url.lower()

        reconnect_count = 0
        max_reconnect = 10
        segment_index = 1
        logger.info(self._log_message("开始录制: %s"), file_name)
        start_timestamp = time.time()
        process = None

        stop_event = asyncio.Event()
        renew_task = asyncio.create_task(self._renew_lock_loop(stop_event))
        # data_task = asyncio.create_task(self._collect_live_data_loop(log_id))
        try:
            while reconnect_count < max_reconnect:
                if is_m3u8:
                    output_file = f"{file_name}_{segment_index}.ts"
                    cmd = [
                        ffmpeg_path,
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
                        "-headers", headers_str,
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
                    self.recording_started(log_id)
                    try:
                        return_code = await process.wait()
                    finally:
                        self.recording_reconnecting(log_id)
                    logger.info(self._log_message("流断开，return_code: %s"), return_code)

                    import os

                    if os.path.exists(output_file) and os.path.getsize(output_file) > 1024:
                        segment_index += 1
                        reconnect_count = 0
                        logger.info(self._log_message("有效分段: %s"), output_file)
                    else:
                        if os.path.exists(output_file):
                            os.remove(output_file)

                    offline_confirm = 0
                    for _ in range(3):
                        await asyncio.sleep(3)
                        live_info = await self.check_live_status()
                        if not live_info.get("is_live"):
                            offline_confirm += 1

                    if offline_confirm >= 3:
                        logger.info(self._log_message("确认主播下播"))
                        break

                    reconnect_count += 1
                    wait_time = min(5 * reconnect_count, 30)
                    logger.warning(self._log_message("断流，%s秒后重连 (%s/%s)"), wait_time, reconnect_count, max_reconnect)
                    await asyncio.sleep(wait_time)
                    stream_url = await DouyuLiveChecker.get_stream_url(self.room_id)
                    is_m3u8 = ".m3u8" in stream_url.lower()
                except Exception as e:
                    logger.exception(self._log_message("录制异常: %s"), e)
                    reconnect_count += 1
                    await asyncio.sleep(5)
        finally:
            self.recording_finished(log_id)
            renew_task.cancel()
            # data_task.cancel()
            # try:
            #     await data_task
            # except asyncio.CancelledError:
            #     pass

            if process and process.returncode is None:
                try:
                    process.terminate()
                    logger.info(self._log_message("清理遗留 FFmpeg 进程"))
                except Exception:
                    pass

            await self.release_record_lock()

            end_time = datetime.now()
            live_seconds = int(time.time() - start_timestamp)
            # max_online_count = await self._get_max_online_count(log_id)
            # last_total_user_count = await self._get_last_total_user_count(log_id)

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
                    "user_num": 0,
                    "total_user": 0,
                    "id": log_id
                })
                await db.commit()

            logger.info(self._log_message("%s 直播结束"), file_name)
            await self._post_process(file_name, segment_index, log_id)

    async def _renew_lock_loop(self, stop_event: asyncio.Event):
        try:
            while True:
                await asyncio.sleep(30)
                success = await self.renew_record_lock()
                if not success:
                    stop_event.set()
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception(self._log_message("续锁任务发生异常: %s"), e)
            stop_event.set()

    # async def _collect_live_data_loop(self, log_id):
    #     try:
    #         while True:
    #             await asyncio.sleep(300)
    #             info = await DouyuLiveChecker.get_room_info(self.room_id)
    #             room_info = info.get("room") or {}
    #             if not room_info:
    #                 continue
    #
    #             try:
    #                 online_count = room_info.get("online")
    #                 like_count = room_info.get("fans_num") or 0
    #                 total_user_count = room_info.get("hn") or room_info.get("hot") or online_count
    #             except (KeyError, TypeError) as e:
    #                 logger.warning("Douyu stats missing key: %s, skipping", e)
    #                 continue
    #
    #             async with get_db_session(self.app) as db:
    #                 await db.execute(text("""
    #                     INSERT INTO live_room_stats
    #                         (live_room_id, live_room_log_id, online_count, like_count, watch_user_count, collect_time)
    #                     VALUES (:live_room_id, :log_id, :online, :like, :watch, CURRENT_TIMESTAMP)
    #                 """), {
    #                     "live_room_id": self.room["id"],
    #                     "log_id": log_id,
    #                     "online": online_count,
    #                     "like": like_count,
    #                     "watch": total_user_count
    #                 })
    #                 await db.commit()
    #     except asyncio.CancelledError:
    #         logger.info("数据采集任务结束")
