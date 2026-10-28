import asyncio
import copy
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
import io
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
import zipfile

from sqlalchemy import text

from app.core.paths import ROOT_DIR
from app.modules.observability.redaction import export_safe, redact
from app.modules.recording.disk import get_disk_guard
from app.modules.recording.status import get_recording_status
from app.modules.recording.tasks import get_recording_tasks
from app.modules.settings.service import resolve_save_path
from app.services.platforms.recorder import get_ffmpeg_path
from app.services.platforms.recorder.base_recorder import BaseRecorder


HARDWARE_ENCODERS = {"h264_nvenc", "hevc_nvenc", "h264_qsv", "hevc_qsv", "h264_amf", "hevc_amf", "h264_videotoolbox", "hevc_videotoolbox"}
ADVICE = {
    "recording_health": "检查网络和直播源；可调整健康超时。恢复耗尽时先排查原因，再重新启用监控。",
    "disk_space": "释放保存盘空间，检查保存目录权限；不要删除正在写入的分片。",
    "ffmpeg_exit": "检查 FFmpeg 错误、直播源及编码器；不确定时运行环境诊断。",
    "live_check": "检查网络、平台配置及接口状态。请求失败不能直接确定是 Cookie 失效。",
    "processing": "检查源文件、目标目录、编码器和容器是否兼容。",
    "database": "检查数据库结构、数据约束、所在磁盘空间及文件权限。",
    "unclassified": "展开异常堆栈，结合关联房间、任务和发生时间检查上下文。",
}


def issues(store, room_id=None):
    events = store.query(room_id=room_id, minimum_level=30, limit=1000)["entries"]
    grouped = {}
    for event in events:
        code = event.get("event_code", "unclassified")
        key = (code, event.get("room_id"), event.get("processing_job_id"), event["message"])
        if key not in grouped:
            grouped[key] = {"id": event["id"], "code": code, "level": event["level"], "room_id": event.get("room_id"),
                            "processing_job_id": event.get("processing_job_id"), "message": event["message"],
                            "last_seen": event["timestamp"], "first_seen": event["timestamp"], "count": 0,
                            "advice": ADVICE.get(code, ADVICE["unclassified"])}
        grouped[key]["count"] += 1
        grouped[key]["first_seen"] = event["timestamp"]
    return {"issues": list(grouped.values())[:100], "scope": "最近 1000 条警告与错误，不代表当前仍未解决"}


async def capture(command, timeout=8):
    process = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
        if process.returncode:
            raise ValueError(stderr.decode("utf-8", errors="replace")[-2000:] or "命令执行失败")
        return stdout.decode("utf-8", errors="replace")[:20000]
    finally:
        await BaseRecorder.stop_process(None, process)


def write_probe(directory):
    if not directory.is_dir():
        raise OSError("保存目录尚未创建或不可用")
    with tempfile.TemporaryFile(dir=directory) as stream:
        stream.write(b"LiveRecorder diagnostic write test")
        stream.flush()


async def diagnose(app, store, test_write=False):
    checks = []

    async def check(key, label, function):
        try:
            detail = await asyncio.wait_for(function(), timeout=12)
            checks.append({"key": key, "label": label, "status": "ok", "detail": redact(detail, store.secrets)})
        except Exception as exc:
            checks.append({"key": key, "label": label, "status": "failed", "detail": redact(str(exc) or "检查超时", store.secrets)})

    async def database():
        async with app.state.db() as db:
            await db.execute(text("SELECT 1"))
        return "数据库连接及只读查询正常"

    async def tool(name):
        executable = get_ffmpeg_path()
        if name == "ffprobe":
            executable = str(Path(executable).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe"))
        return (await capture([executable, "-version"])).splitlines()[0]

    await asyncio.gather(check("database", "SQLite", database), check("ffmpeg", "FFmpeg", lambda: tool("ffmpeg")),
                         check("ffprobe", "FFprobe", lambda: tool("ffprobe")))
    disks = await get_disk_guard(app).snapshot()
    for index, disk in enumerate(disks["disks"]):
        checks.append({"key": f"disk_{index}", "label": "录制磁盘", "status": "failed" if disk["state"] in {"critical", "unavailable"} else "warning" if disk["state"] in {"warning", "disabled"} else "ok",
                       "detail": f'{disk["path"]}: {disk["message"]}', "free_bytes": disk["free_bytes"]})
    if test_write:
        async def writable():
            await asyncio.to_thread(write_probe, resolve_save_path(app.state.recording_settings.settings.save_path))
            return "临时文件写入成功，已清理"
        await check("write", "保存目录写入", writable)
    else:
        checks.append({"key": "write", "label": "保存目录写入", "status": "unchecked", "detail": "未执行写入测试"})
    checks.append({"key": "logging", "label": "日志保存", "status": "warning" if store.write_error or store.dropped else "ok",
                   "detail": store.write_error or f"队列丢弃 {store.dropped} 条；日志文件轮转上限 {store.backups + 1} 份"})
    try:
        capabilities = await asyncio.wait_for(app.state.video_processing.capabilities(), 12)
    except Exception:
        capabilities = {"encoders": [], "error": "编码器检测失败"}
    packages = {}
    for name in ("fastapi", "uvicorn", "SQLAlchemy", "aiosqlite"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = "unknown"
    return {"checked_at": datetime.now(timezone.utc).isoformat(), "checks": checks,
            "environment": {"system": platform.system(), "release": platform.release(), "architecture": platform.machine(),
                            "python": platform.python_version(), "frozen": bool(getattr(sys, "frozen", False)), "packages": packages},
            "encoders": capabilities, "recording": get_recording_status(app).snapshot(),
            "tasks": {"checks": len(get_recording_tasks(app).checks), "recordings": len(get_recording_tasks(app).tasks),
                      "processing": sum(job["status"] in {"queued", "running", "cancelling"} for job in app.state.video_processing.jobs.values())}}


def diagnostic_archive(app, store, filters=None, recording_snapshot=None):
    entries = store.query(**{**(filters or {}), "limit": 500})["entries"]
    settings = app.state.recording_settings.settings.model_dump()
    room_id = (filters or {}).get("room_id")
    snapshot = recording_snapshot if recording_snapshot is not None else get_recording_status(app).snapshot()
    previous = copy.deepcopy(getattr(app.state, "last_diagnostics", None))
    if room_id is not None:
        snapshot = {key: value for key, value in snapshot.items() if str(key) == str(room_id)}
        if previous is not None:
            previous["recording"] = {key: value for key, value in previous.get("recording", {}).items() if str(key) == str(room_id)}
    report = {"report": previous, "recording_settings": settings,
              "recording": snapshot, "log_count": len(entries), "dropped": store.dropped,
              "scope": {"room_id": room_id, "global_environment": True, "log_limit": 500},
              "notes": "不包含 Cookie、配置全文、数据库、视频或其他目录文件。环境检查结果仅代表上次手动检查。"}
    roots = [(str(ROOT_DIR), "<DATA_DIR>"), (str(Path.home()), "<HOME>"),
             (str(resolve_save_path(settings["save_path"])), "<RECORD_DIR>")]
    report, entries = export_safe(report, roots, store.secrets), export_safe(entries, roots, store.secrets)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("report.json", json.dumps(report, ensure_ascii=False, indent=2))
        archive.writestr("runtime.jsonl", "\n".join(json.dumps(event, ensure_ascii=False) for event in entries))
        archive.writestr("manifest.txt", "report.json: environment summary and recording settings\nruntime.jsonl: up to 500 redacted log entries\nNo cookies, database, recordings or arbitrary files.\n")
    return output.getvalue()
