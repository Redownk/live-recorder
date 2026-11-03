"""管理轮询任务的生命周期，协调全局停止、录制清理和中断恢复。"""


import asyncio
from app.modules.recording.worker import crawler_loop
from app.modules.recording.tasks import get_recording_tasks
from app.modules.recording.recovery import recover_interrupted_recordings


class CrawlerManager:
    """串行协调全局轮询任务的启动、停止和关闭。"""

    def __init__(self):
        self.app = None
        self.task: asyncio.Task | None = None
        self.running = False
        self.stop_event: asyncio.Event | None = None
        self.control_lock = asyncio.Lock()
        self.stopping = False

    def init_app(self, app):
        """绑定服务启动时创建的应用实例。

        Args:
            app: 提供数据库、录制设置和任务管理器的应用实例。
        """
        self.app = app


    async def start(self):
        """启动轮询任务。

        Returns:
            started 表示启动成功；already running 表示已有轮询任务；
            shutting down 表示应用关闭期间拒绝启动。
        """
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
        """停止轮询与录制任务，并将未结束的录制日志标记为中断。

        Returns:
            有任务需要停止时返回 stopped，否则返回 not running。
        """
        async with self.control_lock:
            manager = get_recording_tasks(self.app)
            had_work = self.status() or bool(manager.tasks)
            self.stopping = True
            # 先阻止新录制启动，再停止轮询和已有录制，避免清理期间产生新任务。
            manager.paused = True
            manager.stopping_all = True
            try:
                try:
                    await self._stop_crawler()
                finally:
                    await manager.stop_all()
                await recover_interrupted_recordings(self.app)
            finally:
                self.stopping = False
                manager.stopping_all = False
            return "stopped" if had_work else "not running"

    async def shutdown(self):
        """禁止新任务启动并关闭轮询，录制任务由应用关闭流程回收。"""
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
        """返回是否仍在轮询或执行全局停止操作。"""
        return self.stopping or (self.task is not None and not self.task.done())


crawler_manager = CrawlerManager()
