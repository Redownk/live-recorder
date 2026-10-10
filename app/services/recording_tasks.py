import asyncio

from app.core.logger import get_logger


logger = get_logger(__name__)


class RecordingTaskManager:
    def __init__(self):
        self.checks = {}
        self.tasks: dict[tuple[str, str], asyncio.Task] = {}
        self.closing = False
        self.paused = False

    def begin_check(self, key):
        if self.closing or self.paused or key in self.checks or self.is_recording(key):
            return None
        token = object()
        self.checks[key] = token
        return token

    def end_check(self, key, token):
        if self.checks.get(key) is token:
            self.checks.pop(key, None)

    def is_recording(self, key):
        task = self.tasks.get(key)
        return task is not None and not task.done()

    def start_recording(self, key, record, finish):
        if self.closing or self.paused or self.is_recording(key):
            return False

        async def run():
            try:
                await record()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("录制任务异常 platform=%s room_id=%s", *key)
            finally:
                try:
                    await finish()
                except Exception:
                    logger.exception("录制任务清理异常 platform=%s room_id=%s", *key)

        task = asyncio.create_task(run(), name=f"record:{key[0]}:{key[1]}")
        self.tasks[key] = task

        def done(completed):
            if self.tasks.get(key) is completed:
                self.tasks.pop(key, None)
            if not completed.cancelled():
                completed.exception()

        task.add_done_callback(done)
        return True

    def resume(self):
        if self.closing:
            return False
        self.paused = False
        return True

    async def stop_all(self):
        self.paused = True
        tasks = list(self.tasks.values())
        for task in tasks:
            if not task.done() and not task.cancelling():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.clear()
        self.checks.clear()

    async def shutdown(self):
        self.closing = True
        await self.stop_all()


def get_recording_tasks(app):
    manager = getattr(app.state, "recording_tasks", None)
    if manager is None:
        manager = RecordingTaskManager()
        app.state.recording_tasks = manager
    return manager
