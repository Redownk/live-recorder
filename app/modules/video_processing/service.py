import asyncio
import json
import math
import os
from pathlib import Path
import tempfile
from uuid import uuid4

from app.core.logger import get_logger
from app.shared.filesystem.browser import VIDEO_EXTENSIONS
from app.services.platforms.recorder import get_ffmpeg_path
from app.services.platforms.recorder.base_recorder import BaseRecorder
from app.modules.settings.service import resolve_save_path
from app.modules.video_processing.schemas import ENCODERS


PRESETS = {"default": (23, "medium", "4M"), "quality": (18, "slow", "8M"), "fast": (28, "fast", "2M")}
ACTIVE = {"queued", "running", "cancelling"}
logger = get_logger(__name__)


def resolve_inputs(options):
    paths = [resolve_save_path(path) for path in options.files]
    if len(set(paths)) != len(paths):
        raise ValueError("不能重复选择同一个文件")
    for path in paths:
        if path.suffix.lower() not in VIDEO_EXTENSIONS or not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"视频不存在、为空或格式不支持: {path.name}")
    return paths


def output_paths(options, inputs):
    directory = inputs[0].parent if options.save_original else resolve_save_path(options.output_directory)
    if not directory.is_dir():
        raise ValueError("输出目录不存在，请先选择已有目录")
    if options.mode == "merge":
        outputs = [directory / f"{options.output_name}.{options.container}"]
    else:
        outputs = [(path.parent if options.save_original else directory) / f"{path.stem}_{options.encoder}.{options.container}" for path in inputs]
    outputs = [path.resolve() for path in outputs]
    if len(set(outputs)) != len(outputs) or any(path in inputs for path in outputs):
        raise ValueError("输出文件重名或与源文件相同，请更换目录或文件名")
    return outputs


def concat_text(paths, durations=None):
    lines = ["ffconcat version 1.0"]
    for index, path in enumerate(paths):
        escaped = path.as_posix().replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
        if durations is not None:
            lines.append(f"duration {durations[index]:.6f}")
    return "\n".join(lines) + "\n"


def codec_arguments(options):
    if options.encoder == "copy":
        return ["-c", "copy"]
    crf, preset, bitrate = PRESETS[options.preset]
    args = ["-c:v", options.encoder, "-c:a", "aac", "-b:a", "192k"]
    if options.encoder in ("libx264", "libx265"):
        args += ["-crf", str(crf), "-preset", preset, "-pix_fmt", "yuv420p"]
    else:
        args += ["-b:v", bitrate]
    return args


class VideoProcessingManager:
    def __init__(self, recording_tasks=None):
        self.jobs = {}
        self.tasks = {}
        self.claims = set()
        self.semaphore = asyncio.Semaphore(1)
        self.closing = False
        self._capabilities = None
        self.recording_tasks = recording_tasks

    def check_inactive(self, paths):
        prefixes = self.recording_tasks.output_prefixes if self.recording_tasks else set()
        for path in paths:
            if any(path.parent == prefix.parent and (path.stem == prefix.name or path.stem.startswith(prefix.name + "_")) for prefix in prefixes):
                raise ValueError(f"文件正在录制或自动合并，请结束录制后再处理: {path.name}")

    async def capture(self, *command):
        process = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), 30)
            if process.returncode:
                raise ValueError(stderr.decode("utf-8", errors="replace")[-2000:] or "FFmpeg 检测失败")
            return stdout
        finally:
            await BaseRecorder.stop_process(self, process)

    async def capabilities(self):
        if self._capabilities is None:
            try:
                raw = (await self.capture(get_ffmpeg_path(), "-hide_banner", "-encoders")).decode("utf-8", errors="replace")
                available = {fields[1] for line in raw.splitlines() if len(fields := line.split()) >= 2 and fields[0].startswith("V")}
                self._capabilities = {"encoders": [{"value": key, "label": label, "available": key == "copy" or key in available} for key, label in ENCODERS.items()], "error": ""}
            except (OSError, RuntimeError, ValueError, asyncio.TimeoutError) as exc:
                return {"encoders": [{"value": key, "label": label, "available": False} for key, label in ENCODERS.items()], "error": str(exc) or "FFmpeg 检测超时"}
        return self._capabilities

    async def probe(self, path):
        executable = Path(get_ffmpeg_path()).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
        data = json.loads(await self.capture(str(executable), "-v", "error", "-protocol_whitelist", "file,pipe", "-show_streams", "-show_format", "-of", "json", str(path)))
        streams = data.get("streams", [])
        if not any(stream.get("codec_type") == "video" for stream in streams):
            raise ValueError(f"没有视频轨道: {path.name}")
        duration = float(data.get("format", {}).get("duration") or 0)
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError(f"无法获取视频时长: {path.name}")
        signature = [tuple(stream.get(key) for key in ("codec_type", "codec_name", "profile", "level", "width", "height", "pix_fmt", "sample_aspect_ratio", "r_frame_rate", "sample_rate", "channels", "channel_layout", "time_base", "extradata_size")) for stream in streams if stream.get("codec_type") in ("video", "audio")]
        return duration, signature

    def submit(self, options):
        if self.closing or sum(job["status"] in ACTIVE for job in self.jobs.values()) >= 10:
            raise ValueError("处理队列已满或服务正在关闭")
        inputs = resolve_inputs(options)
        outputs = output_paths(options, inputs)
        self.check_inactive(inputs + outputs)
        claims = set(inputs + outputs)
        if options.merge_subtitles and options.mode == "merge":
            claims.update(outputs[0].with_suffix(extension) for extension in (".srt", ".ass"))
        if claims & self.claims:
            raise ValueError("文件已被其他处理任务占用")
        for key in list(self.jobs):
            if len(self.jobs) < 100:
                break
            if self.jobs[key]["status"] not in ACTIVE:
                del self.jobs[key]
        job = {"id": uuid4().hex, "mode": options.mode, "status": "queued", "progress": 0, "current_file": "", "files": [str(path) for path in inputs], "outputs": [], "error": "", "warning": ""}
        self.jobs[job["id"]] = job
        self.claims.update(claims)
        task = asyncio.create_task(self.run(job, options, inputs, outputs))
        self.tasks[job["id"]] = task
        logger.info("视频处理加入队列 id=%s mode=%s files=%s", job["id"], options.mode, len(inputs))
        def finished(completed):
            self.claims.difference_update(claims)
            self.tasks.pop(job["id"], None)
            if completed.cancelled():
                job["status"] = "cancelled"
        task.add_done_callback(finished)
        return job

    async def cancel(self, job_id):
        task = self.tasks.get(job_id)
        if task and not task.done():
            self.jobs[job_id]["status"] = "cancelling"
            if not task.cancelling():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            self.jobs[job_id]["status"] = "cancelled"

    async def shutdown(self):
        self.closing = True
        for task in list(self.tasks.values()):
            if not task.done() and not task.cancelling():
                task.cancel()
        await asyncio.gather(*list(self.tasks.values()), return_exceptions=True)

    async def execute(self, args, job, duration, base, span):
        process = await asyncio.create_subprocess_exec(get_ffmpeg_path(), "-hide_banner", "-nostdin", "-n", "-loglevel", "error", "-progress", "pipe:1", "-nostats", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        errors = bytearray()
        async def drain_errors():
            while chunk := await process.stderr.read(4096):
                errors.extend(chunk)
                del errors[:-4000]
        reader = asyncio.create_task(drain_errors())
        try:
            while line := await process.stdout.readline():
                key, _, value = line.decode("utf-8", errors="replace").strip().partition("=")
                if key == "out_time_us":
                    try:
                        job["progress"] = round(min(99, base + min(1, max(0, int(value) / 1000000 / duration)) * span), 1)
                    except ValueError:
                        pass
            await process.wait()
            await reader
            if process.returncode:
                raise ValueError(errors.decode("utf-8", errors="replace") or "FFmpeg 处理失败")
        finally:
            await BaseRecorder.stop_process(self, process)
            await asyncio.gather(reader, return_exceptions=True)

    async def run(self, job, options, inputs, outputs):
        try:
            async with self.semaphore:
                job["status"] = "running"
                self.check_inactive(inputs + outputs)
                logger.info("视频处理开始 id=%s mode=%s", job["id"], options.mode)
                if options.mode == "transcode":
                    capabilities = await self.capabilities()
                    if not any(item["value"] == options.encoder and item["available"] for item in capabilities["encoders"]):
                        raise ValueError(capabilities["error"] or "当前 FFmpeg 不支持所选编码器")
                info = [await self.probe(path) for path in inputs]
                if options.mode == "merge" and any(signature != info[0][1] for _, signature in info[1:]):
                    raise ValueError("视频编码、分辨率或音轨不一致，请先转码为一致格式再合并")
                groups = [(inputs, outputs[0], sum(item[0] for item in info))] if options.mode == "merge" else [([path], output, info[index][0]) for index, (path, output) in enumerate(zip(inputs, outputs))]
                skipped = 0
                for index, (sources, output, duration) in enumerate(groups):
                    job["current_file"] = output.name
                    subtitle_sources = []
                    subtitle_output = None
                    if options.mode == "merge" and options.merge_subtitles:
                        for extension in (".ass", ".srt"):
                            candidates = [path.with_suffix(extension) for path in inputs]
                            if all(path.is_file() and path.stat().st_size for path in candidates):
                                subtitle_sources, subtitle_output = candidates, output.with_suffix(extension)
                                break
                        if not subtitle_sources:
                            raise ValueError("每个视频都需要同名且同格式的 ASS 或 SRT 弹幕/字幕文件")
                        if subtitle_output.suffix == ".ass":
                            headers = [json.loads(await self.capture(str(Path(get_ffmpeg_path()).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")), "-v", "error", "-protocol_whitelist", "file,pipe", "-show_entries", "stream=extradata", "-show_data", "-of", "json", str(path))) for path in subtitle_sources]
                            if any(header != headers[0] for header in headers[1:]):
                                raise ValueError("ASS 字幕样式或脚本头不一致，请先统一样式再合并")
                    targets = [output] + ([subtitle_output] if subtitle_output else [])
                    if options.existing == "skip" and any(path.exists() for path in targets):
                        skipped += 1
                        continue
                    before = [(path.stat().st_size, path.stat().st_mtime_ns) for path in sources]
                    # Stage on the target filesystem; an interrupted job never replaces an existing output.
                    with tempfile.TemporaryDirectory(prefix=".video-processing-", dir=output.parent) as temporary:
                        staging = Path(temporary) / output.name
                        if options.mode == "merge":
                            listing = Path(temporary) / "concat.txt"
                            listing.write_text(concat_text(sources), encoding="utf-8")
                            args = ["-protocol_whitelist", "file,pipe", "-f", "concat", "-safe", "0", "-i", str(listing), "-map", "0:v:0", "-map", "0:a?", "-c", "copy"]
                        else:
                            args = ["-protocol_whitelist", "file,pipe", "-i", str(sources[0]), "-map", "0:v:0", "-map", "0:a?", *codec_arguments(options)]
                        args += ["-map_metadata", "0" if options.keep_metadata else "-1"]
                        if options.container == "mp4":
                            args += ["-movflags", "+faststart"]
                        await self.execute([*args, str(staging)], job, duration, index * 100 / len(groups), 100 / len(groups))
                        if not staging.is_file() or not staging.stat().st_size:
                            raise ValueError("处理未生成有效文件")
                        await self.probe(staging)
                        staged_outputs = [(staging, output)]
                        if subtitle_output:
                            listing = Path(temporary) / "subtitles.txt"
                            listing.write_text(concat_text(subtitle_sources, [item[0] for item in info]), encoding="utf-8")
                            staged_subtitle = Path(temporary) / subtitle_output.name
                            await self.execute(["-protocol_whitelist", "file,pipe", "-f", "concat", "-safe", "0", "-i", str(listing), "-map", "0:s:0", "-c:s", "copy", str(staged_subtitle)], job, duration, 99, 0)
                            if not staged_subtitle.is_file() or not staged_subtitle.stat().st_size:
                                raise ValueError("合并字幕未生成有效文件")
                            staged_outputs.append((staged_subtitle, subtitle_output))
                        for staged, target in staged_outputs:
                            self.check_inactive([target])
                            if options.existing == "overwrite":
                                os.replace(staged, target)
                            else:
                                os.link(staged, target)
                            job["outputs"].append(str(target))
                    if options.remove_source:
                        source = sources[0]
                        self.check_inactive([source])
                        if (source.stat().st_size, source.stat().st_mtime_ns) == before[0]:
                            source.unlink()
                        else:
                            job["warning"] = "源文件在处理期间发生变化，已保留源文件"
                job["progress"] = 100
                job["status"] = "skipped" if skipped == len(groups) else "completed"
                if skipped:
                    job["warning"] = f"跳过 {skipped} 个已有输出" + (f"；{job['warning']}" if job["warning"] else "")
                logger.info("视频处理结束 id=%s status=%s outputs=%s", job["id"], job["status"], job["outputs"])
        except asyncio.CancelledError:
            job["status"] = "cancelled"
            logger.info("视频处理取消 id=%s", job["id"])
            raise
        except Exception as exc:
            job["status"] = "failed"
            job["error"] = str(exc)
            logger.warning("视频处理失败 id=%s error=%s", job["id"], exc)
