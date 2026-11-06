"""适配哔哩哔哩直播状态、播放流和录制流程。"""


import asyncio
import time
from app.core.logger import get_logger
from app.core.log_context import recording_log_context
from app.services.platforms.bilibili.checker import BiliLiveChecker
from app.shared.media.ffmpeg import get_ffmpeg_path
from app.modules.recording.base_recorder import BaseRecorder
from app.modules.recording.commands import build_recording_command
from app.modules.recording.health import RecordingHealthError
from app.modules.recording.disk import DiskSpaceError
from datetime import datetime


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
        }




    async def record(self,live_info):
        start_time= datetime.now()
        output_prefix = await self.create_output_prefix(live_info, start_time)
        stream_url = await self.refresh_stream_url(live_info, None)
        log_id = await self.repository.start_log(
            self.room["id"], self.platform, live_info["owner"], start_time,
        )

        self._log_id = log_id
        await self.record_loop(log_id,output_prefix,stream_url)

    @recording_log_context
    async def record_loop(self,log_id,file_name,stream_url):
        header_dict = BiliLiveChecker.build_fake_headers()
        headers_str = "".join(f"{key}: {value}\r\n" for key, value in header_dict.items())

        ffmpeg_path=get_ffmpeg_path()


        reconnect_count = 0
        max_reconnect = 10
        segment_index = 1
        self.log_recording_plan(file_name)
        start_timestamp = time.monotonic()
        end_reason = "重连次数达到上限"
        process = None

        data_task = asyncio.create_task(self._collect_live_data_loop(log_id))
        try:
            while reconnect_count < max_reconnect:
                output_file, cmd = build_recording_command(
                    ffmpeg_path, stream_url, file_name, segment_index, headers_str,
                )
                try:
                    process = await self.spawn_recording_process(cmd)

                    logger.info(self._log_message("录制进程已启动：分片=%s，PID=%s"), segment_index,
                                getattr(process, "pid", "未知"), extra={"event_code": "recording_start"})
                    self.recording_started(log_id)
                    try:
                        return_code = await self.wait_recording_process(process, output_file, log_id)
                    finally:
                        self.recording_reconnecting(log_id)


                    logger.info(self._log_message("分片录制已结束：分片=%s，退出码=%s"), segment_index, return_code,
                                extra={"event_code": "recording_segment"})

                    segment_advance = await self.complete_recording_segment(output_file, log_id)
                    segment_index += segment_advance
                    if self._segment_health_error is not None:
                        stream_url = await self.recover_recording_stream(stream_url)
                        if stream_url is None:
                            end_reason = "主播已下播"
                            break
                        continue
                    if segment_advance and self._segment_had_data:
                        reconnect_count = 0
                        logger.info(self._log_message("有效录制分片已保留：%s"), output_file, extra={"event_code": "recording_segment"})

                    # ===== 下播三次确认 =====
                    offline_confirm = 0
                    for _ in range(3):
                        await asyncio.sleep(3)
                        live_info = await self.check_live_status()
                        if not live_info.get("is_live"):
                            offline_confirm += 1

                    if offline_confirm >= 3:
                        end_reason = "主播已下播"
                        logger.info(self._log_message("连续 3 次检测未开播，确认主播下播"), extra={"event_code": "live_check"})
                        break

                    # ===== 网络断流重连 =====
                    reconnect_count += 1
                    wait_time = min(5 * reconnect_count, 30)

                    logger.warning(self._log_message("直播流中断，等待 %s 秒后重连（连续重试 %s/%s）"), wait_time, reconnect_count, max_reconnect, extra={"event_code": "recording_retry"})
                    await asyncio.sleep(wait_time)
                    stream_url = await self.refresh_stream_url(live_info, stream_url)

                except (RecordingHealthError, DiskSpaceError):
                    raise
                except Exception as e:
                    logger.exception(self._log_message("录制异常，5 秒后重试（连续重试 %s/%s）：%s"), reconnect_count + 1, max_reconnect, e, extra={"event_code": "recording_retry"})
                    reconnect_count += 1
                    await asyncio.sleep(5)
        except (RecordingHealthError, DiskSpaceError) as exc:
            end_reason = str(exc)
            raise
        finally:
            self.recording_finished(log_id)
            data_task.cancel()
            await asyncio.gather(data_task, return_exceptions=True)
            await self.stop_process(process)

            end_time = datetime.now()
            live_seconds = int(time.monotonic() - start_timestamp)
            max_online_count = await self._get_max_online_count(log_id)
            last_total_user_count = await self._get_last_total_user_count(log_id)

            await self.repository.finish_log(
                log_id, end_time, live_seconds, max_online_count, last_total_user_count,
                interrupted=bool(asyncio.current_task().cancelling()) or self._recovery.failed,
            )

            self.log_recording_end(end_reason, live_seconds, reconnect_count)
            if not asyncio.current_task().cancelling() and not self._recovery.failed:
                await self._post_process(file_name, segment_index,log_id)
            elif self.recording_options().segment_minutes and not self._recovery.failed:
                await self.register_timed_segments(file_name, segment_index, log_id, probe_durations=False)
            else:
                logger.info(self._log_message("原始录制分片已保留，可在视频处理中继续整理"), extra={"event_code": "recording_end"})

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
                    logger.warning(self._log_message("本轮统计字段缺失，跳过采样：%s"), e)
                    continue

                await self.repository.add_stats(
                    self.room["id"], log_id, online_count, like_count, total_user_count,
                )

        except asyncio.CancelledError:
            logger.debug(self._log_message("直播统计采样任务已结束"))
