import asyncio

from app.core.logger import get_logger


logger = get_logger(__name__)


class RecordingTaskManager:
    def __init__(self):
        self.checks = {}
        self.check_tasks = {}
        self.tasks: dict[tuple[str, str], asyncio.Task] = {}
        self.output_prefixes = set()
        self.output_paths = {}
        self.room_ids = {}
        self.phases = {}
        self.notices = {}
        self.disabled_keys = set()
        self.stopping_keys = set()
        self.control_locks = {}
        self.stopping_all = False
        self.closing = False
        self.paused = False

    def allows_start(self, key, manual=False):
        return not (self.closing or self.stopping_all or key in self.stopping_keys
                    or (not manual and (self.paused or key in self.disabled_keys)))

    def control_lock(self, key):
        return self.control_locks.setdefault(key, asyncio.Lock())

    def begin_check(self, key, manual=False):
        if not self.allows_start(key, manual) or key in self.checks or self.is_recording(key):
            return None
        token = object()
        self.checks[key] = token
        return token

    def end_check(self, key, token):
        if self.checks.get(key) is token:
            self.checks.pop(key, None)
            self.check_tasks.pop(key, None)

    def is_recording(self, key):
        task = self.tasks.get(key)
        return task is not None and not task.done()

    def start_recording(self, key, record, finish, *, token=None, manual=False):
        if (not self.allows_start(key, manual) or self.is_recording(key)
                or (token is not None and self.checks.get(key) is not token)):
            return False

        async def run():
            try:
                await record()
            except asyncio.CancelledError:
                raise
            except OSError as exc:
                from app.modules.recording.disk import DiskSpaceError

                if isinstance(exc, DiskSpaceError):
                    self.notices[key] = {"state": "disk_blocked", "message": str(exc)}
                    logger.warning("磁盘保护阻止录制 platform=%s room_id=%s: %s", *key, exc)
                else:
                    logger.exception("录制任务异常 platform=%s room_id=%s", *key)
            except Exception:
                logger.exception("录制任务异常 platform=%s room_id=%s", *key)
            finally:
                try:
                    await finish()
                except Exception:
                    logger.exception("录制任务清理异常 platform=%s room_id=%s", *key)

        task = asyncio.create_task(run(), name=f"record:{key[0]}:{key[1]}")
        self.tasks[key] = task
        self.phases[key] = "preparing"
        self.notices.pop(key, None)

        def done(completed):
            if self.tasks.get(key) is completed:
                self.tasks.pop(key, None)
                self.phases.pop(key, None)
            if not completed.cancelled():
                completed.exception()

        task.add_done_callback(done)
        return True

    async def stop_room(self, key, *, reason=None, message=None):
        self.stopping_keys.add(key)
        try:
            self.checks.pop(key, None)
            check = self.check_tasks.pop(key, None)
            task = self.tasks.get(key)
            pending = [item for item in (check, task) if item is not None]
            for item in pending:
                if not item.done() and not item.cancelling():
                    item.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            if reason:
                self.notices[key] = {"state": reason, "message": message}
        finally:
            self.stopping_keys.discard(key)

    def control_snapshot(self):
        result = {}
        for key, room_id in self.room_ids.items():
            if key in self.stopping_keys:
                state = {"state": "stopping"}
            elif key in self.checks:
                state = {"state": "checking"}
            elif self.is_recording(key):
                state = {"state": self.phases.get(key, "preparing")}
            else:
                state = self.notices.get(key)
            if state:
                result[room_id] = {**state, "elapsed_seconds": 0}
        return result

    def resume(self):
        if self.closing:
            return False
        self.paused = False
        return True

    async def stop_all(self):
        self.paused = True
        was_stopping = self.stopping_all
        self.stopping_all = True
        try:
            tasks = list(self.tasks.values()) + list(self.check_tasks.values())
            self.checks.clear()
            for task in tasks:
                if not task.done() and not task.cancelling():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.tasks.clear()
            self.check_tasks.clear()
            self.output_prefixes.clear()
            self.output_paths.clear()
        finally:
            self.stopping_all = was_stopping

    async def shutdown(self):
        self.closing = True
        await self.stop_all()


def get_recording_tasks(app):
    manager = getattr(app.state, "recording_tasks", None)
    if manager is None:
        manager = RecordingTaskManager()
        app.state.recording_tasks = manager
    return manager
