import time
from datetime import datetime
import asyncio
from pathlib import Path
from uuid import uuid4

from app.core.session import get_db_session
from app.core.logger import get_logger
from app.services.platforms.recorder import get_ffmpeg_path
from app.models import LiveRoomLogVideo
from app.services.recording_settings import create_output_prefix
from app.services.recording_status import get_recording_status
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
        self._check_lock_token = uuid4().hex
        return await redis_client.set(
            f"lock:check:{self.platform}:{self.room_id}",
            self._check_lock_token,
            nx=True,
            ex=max(60, self.app.state.recording_settings.settings.check_interval_seconds)
        )

    async def release_check_lock(self):
        await self.app.state.redis.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end",
            1,
            f"lock:check:{self.platform}:{self.room_id}",
            self._check_lock_token,
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
        try:
            live_info = await self.check_live_status()
        finally:
            await self.release_check_lock()

        if not live_info["is_live"]:
            logger.info(self._log_message("未开播，跳过录制: %s"), live_info)
            return

        if not await self.acquire_record_lock():
            logger.info(self._log_message("获取录制锁失败，跳过"))
            return

        logger.info(self._log_message("检测到开播，开始录制: %s"), live_info.get("title") or live_info.get("owner"))
        try:
            await self.record(live_info)
        except BaseException:
            await self.release_record_lock()
            raise

    async def check_live_status(self):
        raise NotImplementedError

    async def record(self, live_info):
        raise NotImplementedError

    async def create_output_prefix(self, live_info, start_time):
        return await create_output_prefix(self.app, self.room, live_info, start_time)

    def recording_started(self, log_id):
        get_recording_status(self.app).started(self.room["id"], log_id)

    def recording_reconnecting(self, log_id):
        get_recording_status(self.app).reconnecting(self.room["id"], log_id)

    def recording_finished(self, log_id):
        get_recording_status(self.app).finished(self.room["id"], log_id)

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

    async def _post_process(self, file_name, segment_count, log_id):

        import os

        logger.info(self._log_message("开始后处理"))

        if segment_count <= 0:
            logger.info(self._log_message("没有分段文件，跳过处理"))
            return

        segments = []
        for extension in ("ts", "flv"):
            segments = [Path(f"{file_name}_{i}.{extension}") for i in range(1, segment_count + 1)]
            segments = [path for path in segments if path.is_file() and path.stat().st_size > 0]
            if segments:
                ext = extension
                break
        if not segments:
            logger.info(self._log_message("没有有效分段文件，跳过处理"))
            return

        ffmpeg_path = get_ffmpeg_path()
        list_file = f"{file_name}_filelist.txt"

        with open(list_file, "w", encoding="utf-8") as f:
            for segment in segments:
                escaped_path = segment.resolve().as_posix().replace("'", "'\\''")
                f.write(f"file '{escaped_path}'\n")

        merged_file = f"{file_name}.{ext}"

        logger.info(self._log_message("开始合并分段"))

        merge_cmd = [
            ffmpeg_path,
            "-nostdin", "-n",
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
        return_code = await process.wait()

        if return_code != 0 or not os.path.isfile(merged_file) or os.path.getsize(merged_file) == 0:
            logger.warning(self._log_message("合并失败，保留分段文件，退出码: %s"), return_code)
            return

        logger.info(self._log_message("分段合并完成"))

        # Register the local video before cleaning up recording segments.
        try:

            # 获取文件大小 (byte)
            file_size = os.path.getsize(merged_file)

            # 使用 ffprobe 获取时长 (秒)
            duration = 0
            probe_cmd = [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", merged_file
            ]

            try:
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
                    logger.warning("ffprobe 错误: %s", stderr.decode("utf-8", errors="replace"))
            except (OSError, ValueError) as exc:
                logger.warning(self._log_message("视频时长读取失败: %s"), exc)

            async with get_db_session(self.app) as db:
                db.add(LiveRoomLogVideo(
                    live_room_id=self.room["id"],
                    live_room_log_id=log_id,
                    file_name=os.path.basename(merged_file),
                    file_path=str(Path(merged_file).resolve()),
                    file_size=file_size,
                    duration=duration,
                ))
                await db.commit()
            logger.info(self._log_message("本地视频已保存: %s"), merged_file)

        except Exception as e:
            logger.exception(self._log_message("本地视频登记失败，保留录制文件: %s"), e)
            return

        logger.info(self._log_message("开始清理临时文件"))
        try:
            os.remove(list_file)
            for segment in segments:
                segment.unlink()

            logger.info(self._log_message("临时文件清理完成"))

        except Exception as e:
            logger.exception(self._log_message("清理文件失败: %s"), e)

        logger.info(self._log_message("后处理完成"))
