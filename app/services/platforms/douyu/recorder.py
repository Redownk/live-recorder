"""适配斗鱼直播状态、播放流刷新和录制流程。"""


import asyncio
import time
from datetime import datetime


from app.core.logger import get_logger
from app.core.log_context import recording_log_context
from app.services.platforms.douyu.checker import DouyuLiveChecker
from app.shared.media.ffmpeg import get_ffmpeg_path
from app.modules.recording.base_recorder import BaseRecorder
from app.modules.recording.commands import build_recording_command
from app.modules.recording.health import RecordingHealthError
from app.modules.recording.disk import DiskSpaceError


logger = get_logger(__name__)


class DouyuRecorder(BaseRecorder):

    async def refresh_stream_url(self, live_info, previous_url):
        return await DouyuLiveChecker.get_stream_url(self.room_id, quality=self.recording_options().quality)

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
        }

    async def record(self, live_info):
        start_time = datetime.now()
        output_prefix = await self.create_output_prefix(live_info, start_time)

        stream_url = await self.refresh_stream_url(live_info, None)

        log_id = await self.repository.start_log(
            self.room["id"], self.platform, live_info["owner"], start_time,
        )

        self._log_id = log_id
        await self.record_loop(log_id, output_prefix, stream_url)

    @recording_log_context
    async def record_loop(self, log_id, file_name, stream_url):
        header_dict = DouyuLiveChecker.build_fake_headers()
        headers_str = "".join(f"{key}: {value}\r\n" for key, value in header_dict.items() if value)

        ffmpeg_path = get_ffmpeg_path()

        reconnect_count = 0
        max_reconnect = 10
        segment_index = 1
        logger.info(self._log_message("开始录制: %s"), file_name)
        start_timestamp = time.time()
        process = None

        try:
            while reconnect_count < max_reconnect:
                output_file, cmd = build_recording_command(
                    ffmpeg_path, stream_url, file_name, segment_index, headers_str,
                )
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
                    stream_url = await self.refresh_stream_url(live_info, stream_url)
                    is_m3u8 = ".m3u8" in stream_url.lower()
                except (RecordingHealthError, DiskSpaceError):
                    raise
                except Exception as e:
                    logger.exception(self._log_message("录制异常: %s"), e)
                    reconnect_count += 1
                    await asyncio.sleep(5)
        finally:
            self.recording_finished(log_id)
            await self.stop_process(process)

            end_time = datetime.now()
            live_seconds = int(time.time() - start_timestamp)

            await self.repository.finish_log(
                log_id, end_time, live_seconds, 0, 0,
                interrupted=bool(asyncio.current_task().cancelling()) or self._recovery.failed,
            )

            logger.info(self._log_message("%s 直播结束"), file_name)
            if not asyncio.current_task().cancelling() and not self._recovery.failed:
                await self._post_process(file_name, segment_index, log_id)
            elif self.recording_options().segment_minutes and not self._recovery.failed:
                await self.register_timed_segments(file_name, segment_index, log_id, probe_durations=False)
            else:
                logger.info(self._log_message("录制已中断，保留分片文件"))
