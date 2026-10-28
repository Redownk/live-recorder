import asyncio
import shutil
from pathlib import Path

from app.core.logger import get_logger
from app.modules.recording.tasks import get_recording_tasks
from app.modules.settings.service import resolve_save_path


logger = get_logger(__name__)
GIB = 1024 ** 3


class DiskSpaceError(OSError):
    pass


def inspect_disk(directory):
    path = Path(directory).resolve()
    probe = path
    # The configured directory may not exist until the first recording.
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    if not probe.is_dir():
        raise OSError("保存路径不是目录")
    usage = shutil.disk_usage(probe)
    return {"path": str(path), "total_bytes": usage.total, "used_bytes": usage.used, "free_bytes": usage.free}


class RecordingDiskGuard:
    def __init__(self, app):
        self.app = app
        self.task = None
        self.stopped = asyncio.Event()

    async def inspect(self, directory):
        options = self.app.state.recording_settings.settings
        try:
            disk = await asyncio.to_thread(inspect_disk, directory)
        except (OSError, ValueError, RuntimeError):
            return {"path": str(directory), "total_bytes": None, "used_bytes": None, "free_bytes": None,
                    "state": "unavailable" if options.disk_protection_enabled else "disabled",
                    "message": "无法读取磁盘容量，已暂停录制" if options.disk_protection_enabled else "无法读取磁盘容量，空间保护已关闭"}
        free = disk["free_bytes"]
        if not options.disk_protection_enabled:
            state, message = "disabled", "磁盘空间保护已关闭"
        elif free <= options.disk_stop_free_gb * GIB:
            state, message = "critical", "磁盘空间严重不足，已禁止新录制，将停止该目录上的录制"
        elif free < options.disk_min_free_gb * GIB:
            state, message = "warning", "磁盘剩余空间不足，已暂停新录制"
        else:
            state, message = "normal", "磁盘空间正常"
        return {**disk, "state": state, "message": message}

    async def ensure_can_start(self, directory, extra_bytes=0):
        options = self.app.state.recording_settings.settings
        if not options.disk_protection_enabled:
            return
        disk = await self.inspect(directory)
        if disk["state"] != "normal":
            raise DiskSpaceError(f'{disk["message"]}: {directory}')
        if disk["free_bytes"] - extra_bytes <= options.disk_stop_free_gb * GIB:
            raise DiskSpaceError("磁盘空间不足以安全完成分片合并，保留原分片")

    async def snapshot(self):
        options = self.app.state.recording_settings.settings
        paths = {resolve_save_path(options.save_path)}
        paths.update(path.parent for path in get_recording_tasks(self.app).output_paths.values())
        disks = [await self.inspect(path) for path in sorted(paths, key=str)]
        return {"enabled": options.disk_protection_enabled, "min_free_gb": options.disk_min_free_gb,
                "stop_free_gb": options.disk_stop_free_gb, "disks": disks}

    async def check_once(self):
        if not self.app.state.recording_settings.settings.disk_protection_enabled:
            return
        manager = get_recording_tasks(self.app)
        for key, prefix in list(manager.output_paths.items()):
            if self.stopped.is_set():
                break
            disk = await self.inspect(prefix.parent)
            # Only cancel the task associated with the path we inspected, not a replacement task.
            if disk["state"] in {"critical", "unavailable"} and manager.output_paths.get(key) == prefix:
                async with manager.control_lock(key):
                    if manager.output_paths.get(key) == prefix:
                        logger.warning("磁盘保护停止录制 platform=%s room_id=%s path=%s", *key, prefix.parent,
                                       extra={"room_id": manager.room_ids.get(key), "platform": key[0], "platform_room_id": key[1], "event_code": "disk_space"})
                        await manager.stop_room(key, reason="disk_blocked", message=disk["message"])

    async def run(self):
        while not self.stopped.is_set():
            try:
                await self.check_once()
            except Exception:
                logger.exception("磁盘空间保护检查失败")
            try:
                await asyncio.wait_for(self.stopped.wait(), timeout=5)
            except TimeoutError:
                pass

    def start(self):
        if self.task is None or self.task.done():
            self.stopped.clear()
            self.task = asyncio.create_task(self.run(), name="recording-disk-guard")

    async def shutdown(self):
        if self.task is not None:
            # Let any in-progress room cleanup finish without a second cancellation.
            self.stopped.set()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None


def get_disk_guard(app):
    guard = getattr(app.state, "recording_disk_guard", None)
    if guard is None:
        guard = RecordingDiskGuard(app)
        app.state.recording_disk_guard = guard
    return guard
