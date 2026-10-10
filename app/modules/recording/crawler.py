
import asyncio
from app.modules.recording.worker import crawler_loop
from app.modules.recording.tasks import get_recording_tasks
from app.modules.recording.recovery import recover_interrupted_recordings


class CrawlerManager:

    def __init__(self):
        self.app = None
        self.task: asyncio.Task | None = None
        self.running = False
        self.stop_event: asyncio.Event | None = None
        self.control_lock = asyncio.Lock()
        self.stopping = False

    def init_app(self, app):
        """
        在 main 里调用
        """
        self.app = app


    async def start(self):
        async with self.control_lock:
            if self.task is not None and not self.task.done():
                return "already running"
            if not get_recording_tasks(self.app).resume():
                return "shutting down"
            self.stop_event = asyncio.Event()
            self.task = asyncio.create_task(crawler_loop(self.app, self.stop_event))
            self.running = True
            return "started"

    async def stop(self):
        async with self.control_lock:
            manager = get_recording_tasks(self.app)
            had_work = self.status() or bool(manager.tasks)
            self.stopping = True
            manager.paused = True
            try:
                try:
                    await self._stop_crawler()
                finally:
                    await manager.stop_all()
                await recover_interrupted_recordings(self.app)
            finally:
                self.stopping = False
            return "stopped" if had_work else "not running"

    async def shutdown(self):
        async with self.control_lock:
            get_recording_tasks(self.app).closing = True
            await self._stop_crawler()

    async def _stop_crawler(self):
        if self.stop_event is not None:
            self.stop_event.set()
        if self.task is not None:
            if not self.task.done():
                self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        self.task = None
        self.running = False

    def status(self):
        return self.stopping or (self.task is not None and not self.task.done())


crawler_manager = CrawlerManager()
