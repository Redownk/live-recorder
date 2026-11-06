"""适配抖音直播状态和画质选择，执行录制并定期采集直播统计。"""


import asyncio
import json
import time
from datetime import datetime

from app.core.logger import get_logger
from app.core.log_context import recording_log_context
from app.services.platforms.douyin.checker import DouyinLiveChecker
from app.modules.recording.base_recorder import BaseRecorder
from app.modules.recording.commands import build_recording_command
from app.modules.recording.health import RecordingHealthError
from app.modules.recording.disk import DiskSpaceError
from app.modules.recording.quality import douyin_stream
from app.shared.media.ffmpeg import get_ffmpeg_path


logger = get_logger(__name__)


class DouyinRecorder(BaseRecorder):

    async def refresh_stream_url(self, live_info, previous_url):
        return douyin_stream(live_info, self.recording_options().quality)

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
                "streams": {}
            }

        room_data = room_list[0]

        if not room_data.get("stream_url"):
            return {
                "is_live": False,
                "owner": user_data.get("nickname", ""),
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
            "avatar": ((user_data.get("avatar_thumb") or {}).get("url_list") or [""])[0],
            "cover": ((room_data.get("cover") or {}).get("url_list") or [""])[0],
            "streams": streams
        }

    #启动录制
    async def record(self, live_info):

        start_time = datetime.now()
        output_prefix = await self.create_output_prefix(live_info, start_time)

        priority = ["real_origin", "origin", "uhd", "hd", "sd", "ld", "ao"]

        selected_q = None
        for q in priority:
            if q in live_info["streams"]:
                selected_q = q
                break

        if not selected_q:
            logger.warning(self._log_message("没有可用清晰度"))
            return

        stream_url = douyin_stream(live_info, self.recording_options().quality)

        # 写入数据库日志
        log_id = await self.repository.start_log(
            self.room["id"], self.platform, live_info["owner"], start_time,
        )

        self._log_id = log_id
        await self.record_loop(log_id, output_prefix, stream_url)

    #异步录制任务
    @recording_log_context
    async def record_loop(self, log_id, file_name, stream_url):
        headers = (
            "Referer: https://live.douyin.com/\r\n"
            "Origin: https://live.douyin.com\r\n"
            "User-Agent: Mozilla/5.0\r\n"
        )
        ffmpeg_path = get_ffmpeg_path()
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
                    ffmpeg_path, stream_url, file_name, segment_index, headers,
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
                    # 下播三次确认
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
                    # 网络断流重连
                    reconnect_count += 1
                    wait_time = min(5 * reconnect_count, 30)

                    logger.warning(self._log_message("直播流中断，等待 %s 秒后重连（连续重试 %s/%s）"), wait_time, reconnect_count, max_reconnect, extra={"event_code": "recording_retry"})
                    await asyncio.sleep(wait_time)
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
                    logger.warning(self._log_message("本轮统计字段缺失，跳过采样：%s"), e)
                    continue

                await self.repository.add_stats(
                    self.room["id"], log_id, online_count, like_count, total_user_count,
                )

        except asyncio.CancelledError:
            logger.debug(self._log_message("直播统计采样任务已结束"))
