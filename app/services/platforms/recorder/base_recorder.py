import time
from datetime import datetime
import asyncio

from app.core.session import get_db_session
from app.core.logger import get_logger
from app.core.config import local_config
from app.services.platforms.recorder import get_ffmpeg_path
from app.utils.oss_uploader import upload_file
from sqlalchemy import text


logger = get_logger(__name__)

class BaseRecorder:

    def __init__(self, app, room):
        self.app = app
        self.room = room
        self.room_id = room["room_id"]
        self.platform = room["platform"]

    def _log_message(self, message: str) -> str:
        return f"[platform={self.platform} room_id={self.room_id}] {message}"

    async def acquire_check_lock(self):
        redis_client = self.app.state.redis
        return await redis_client.set(
            f"lock:check:{self.platform}:{self.room_id}",
            "1",
            nx=True,
            ex=60
        )

    async def acquire_record_lock(self):
        redis_client = self.app.state.redis
        return await redis_client.set(
            f"lock:record:{self.platform}:{self.room_id}",
            "1",
            nx=True,
            ex=120
        )

    async def renew_record_lock(self):
        redis_client = self.app.state.redis
        result=await redis_client.expire(f"lock:record:{self.platform}:{self.room_id}", 120)
        return result > 0

    async def release_record_lock(self):
        redis_client = self.app.state.redis
        await redis_client.delete(f"lock:record:{self.platform}:{self.room_id}")

    async def start(self):
        redis_client = self.app.state.redis
        if redis_client is None:
            logger.warning(self._log_message("Redis 未连接，跳过录制检查"))
            return

        if await redis_client.exists(f"lock:record:{self.platform}:{self.room_id}"):
            logger.info(self._log_message("录制锁已存在，跳过"))
            return

        if not await self.acquire_check_lock():
            logger.info(self._log_message("检查锁已存在，跳过"))
            return

        logger.info(self._log_message("开始检测直播状态"))
        live_info = await self.check_live_status()

        if not live_info["is_live"]:
            logger.info(self._log_message("未开播，跳过录制: %s"), live_info)
            return

        if not await self.acquire_record_lock():
            logger.info(self._log_message("获取录制锁失败，跳过"))
            return

        logger.info(self._log_message("检测到开播，开始录制: %s"), live_info.get("title") or live_info.get("owner"))
        await self.record(live_info)

    async def check_live_status(self):
        raise NotImplementedError

    async def record(self, live_info):
        raise NotImplementedError

    async def _get_max_online_count(self, log_id):
        async with get_db_session(self.app) as db:
            result = await db.execute(text("""
                SELECT MAX(online_count)
                FROM live_room_stats
                WHERE live_room_log_id = :log_id
            """), {
                "log_id": log_id
            })
            return result.scalar()

    async def _get_last_total_user_count(self, log_id):
        async with get_db_session(self.app) as db:
            result = await db.execute(text("""
                SELECT watch_user_count
                FROM live_room_stats
                WHERE live_room_log_id = :log_id
                ORDER BY collect_time DESC, id DESC
                LIMIT 1
            """), {
                "log_id": log_id
            })
            return result.scalar()

    def _build_transcode_command(self, ffmpeg_path, merged_file, mp4_file):
        gpu_type = str(local_config.get("transcode", {}).get("gpu", "nvidia")).strip().lower()

        codec_map = {
            "nvidia": {
                "codec": "hevc_nvenc",
                "options": ["-preset", "p5", "-rc", "vbr", "-cq", "28", "-b:v", "0"],
            },
            "intel": {
                "codec": "hevc_qsv",
                "options": ["-preset", "slow", "-global_quality", "28", "-look_ahead", "1"],
            },
            "amd": {
                "codec": "hevc_amf",
                "options": ["-quality", "balanced", "-rc", "qvbr", "-qvbr_quality_level", "28"],
            },
        }

        selected = codec_map.get(gpu_type)
        if selected is None:
            logger.warning(self._log_message("未知转码显卡配置 gpu=%s，已回退到 nvidia"), gpu_type)
            gpu_type = "nvidia"
            selected = codec_map[gpu_type]

        logger.info(self._log_message("本次转码使用显卡类型: %s, 编码器: %s"), gpu_type, selected["codec"])

        return [
            ffmpeg_path,
            "-i", merged_file,
            "-c:v", selected["codec"],
            *selected["options"],
            "-tag:v", "hvc1",
            "-c:a", "aac",
            "-b:a", "96k",
            "-movflags", "+faststart",
            mp4_file
        ]

    async def _post_process(self, file_name, segment_count,log_id):

        import os
        ffmpeg_path = get_ffmpeg_path()
        transcode_enabled = bool(local_config.get("transcode", {}).get("enable", True))

        logger.info(self._log_message("开始后处理"))

        if segment_count <= 0:
            logger.info(self._log_message("没有分段文件，跳过处理"))
            return

        # ==============================
        # 1️⃣ 判断文件类型
        # ==============================
        first_ts = f"{file_name}_1.ts"
        is_ts = os.path.exists(first_ts)
        ext = "ts" if is_ts else "flv"

        # ==============================
        # 2️⃣ 生成 concat 文件列表
        # ==============================
        list_file = f"{file_name}_filelist.txt"

        with open(list_file, "w", encoding="utf-8") as f:
            for i in range(1, segment_count + 1):
                segment_file = f"{file_name}_{i}.{ext}"
                if os.path.exists(segment_file):
                    f.write(f"file '{segment_file}'\n")

        merged_file = f"{file_name}_merged.{ext}"

        logger.info(self._log_message("开始合并分段"))

        merge_cmd = [
            ffmpeg_path,
            "-f", "concat",
            "-safe", "0",
            "-i", list_file,
            "-c", "copy",
            merged_file
        ]

        process = await asyncio.create_subprocess_exec(
            *merge_cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await process.wait()

        if not os.path.exists(merged_file):
            logger.warning(self._log_message("合并失败，终止后处理"))
            return

        logger.info(self._log_message("分段合并完成"))
        upload_target_file = merged_file

        # ==============================
        # 3️⃣ 输出 MP4
        # enable=true: H265 压缩转码
        # enable=false: 无损封装为 MP4
        # ==============================
        mp4_file = f"{file_name}.mp4"

        if transcode_enabled:
            logger.info(self._log_message("开始 H265 转码压缩"))
            compress_cmd = self._build_transcode_command(ffmpeg_path, merged_file, mp4_file)

            process = await asyncio.create_subprocess_exec(
                *compress_cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            await process.wait()

            if not os.path.exists(mp4_file):
                logger.warning(self._log_message("压缩失败，保留原始文件"))
                return

            logger.info(self._log_message("H265压缩完成: %s"), mp4_file)
            upload_target_file = mp4_file
        else:
            logger.info(self._log_message("已禁用转码，开始无损封装 MP4: %s"), merged_file)
            remux_cmd = [
                ffmpeg_path,
                "-i", merged_file,
                "-c", "copy",
                "-movflags", "+faststart",
                mp4_file
            ]

            process = await asyncio.create_subprocess_exec(
                *remux_cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            await process.wait()

            if not os.path.exists(mp4_file):
                logger.warning(self._log_message("无损封装 MP4 失败，终止后处理"))
                return

            logger.info(self._log_message("无损封装 MP4 完成: %s"), mp4_file)
            upload_target_file = mp4_file

        # ==============================
        # 4️⃣ 清理临时文件
        # ==============================
        logger.info(self._log_message("开始清理临时文件"))

        try:

            # 获取文件大小 (byte)
            file_size = os.path.getsize(upload_target_file)

            # 使用 ffprobe 获取时长 (秒)
            duration = 0
            probe_cmd = [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", upload_target_file
            ]

            probe_process = await asyncio.create_subprocess_exec(
                *probe_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await probe_process.communicate()

            if probe_process.returncode == 0:
                duration_str = stdout.decode('utf-8').strip()
                if duration_str:
                    duration = int(float(duration_str))
            else:
                logger.warning("ffprobe 错误: %s", stderr.decode("utf-8"))

            logger.info(self._log_message("开始上传OSS"))

            url = await upload_file(self.app, upload_target_file)

            if url:
                logger.info(self._log_message("OSS上传完成: %s"), url)
                async with get_db_session(self.app) as db:
                    await db.execute(text("""
                                          INSERT INTO live_room_log_video (tenant_id, live_room_id, live_room_log_id,
                                                                           file_name, file_url, file_size, duration,
                                                                           create_time, del_flag)
                                          VALUES ('000000', :room_id, :log_id,
                                                  :file_name, :file_url, :file_size, :duration,
                                                  CURRENT_TIMESTAMP, 0)
                                          """), {
                                         "room_id": self.room["id"],
                                         "log_id": log_id,
                                         "file_name": os.path.basename(upload_target_file),
                                         "file_url": url,
                                         "file_size": file_size,
                                         "duration": duration
                                     })
                    await db.commit()
            else:
                logger.warning(self._log_message("OSS上传失败"))

        except Exception as e:
            logger.exception(self._log_message("OSS上传异常: %s"), e)

        try:
            os.remove(list_file)
            # os.remove(merged_file)

            for i in range(1, segment_count + 1):
                segment_file = f"{file_name}_{i}.{ext}"
                if os.path.exists(segment_file):
                    os.remove(segment_file)

            logger.info(self._log_message("临时文件清理完成"))

        except Exception as e:
            logger.exception(self._log_message("清理文件失败: %s"), e)

        logger.info(self._log_message("后处理完成"))
