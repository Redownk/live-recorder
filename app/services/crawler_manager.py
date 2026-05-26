
import asyncio
from app.services.crawler_worker import crawler_loop


class CrawlerManager:

    def __init__(self):
        self.app = None
        self.task: asyncio.Task | None = None
        self.running = False
        self.stop_event: asyncio.Event | None = None

    def init_app(self, app):
        """
        在 main 里调用
        """
        self.app = app


    async def start(self):
        if self.running:
            return "already running"

        self.stop_event = asyncio.Event()

        # 在当前事件循环创建后台任务
        self.task = asyncio.create_task(
            crawler_loop(self.app, self.stop_event)
        )

        self.running = True
        return "started"

    async def stop(self):
        if not self.running:
            return "not running"

        self.stop_event.set()

        if self.task:
            await self.task

        self.running = False
        return "stopped"

    def status(self):
        return self.running


crawler_manager = CrawlerManager()
