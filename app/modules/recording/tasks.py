"""管理直播检查和录制任务，协调同一直播间的并发启动、停止与清理。"""


import asyncio

from app.core.logger import get_logger


logger = get_logger(__name__)


class RecordingTaskManager:
    """管理以平台和房间号为键的直播检查与录制任务。"""

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
        """判断直播间当前是否允许启动检查或录制。

        Args:
            key: 由平台标识和房间号组成的元组。
            manual: 是否为手动启动；手动启动可忽略暂停和禁用监控标记。

        Returns:
            允许启动时为 True；关闭或停止期间始终为 False。
        """
        return not (self.closing or self.stopping_all or key in self.stopping_keys
                    or (not manual and (self.paused or key in self.disabled_keys)))

    def control_lock(self, key):
        return self.control_locks.setdefault(key, asyncio.Lock())

    def begin_check(self, key, manual=False):
        """为一次直播检查申请独占令牌。

        Args:
            key: 由平台标识和房间号组成的元组。
            manual: 是否由用户手动触发检查。

        Returns:
            检查令牌；不允许启动、已在检查或正在录制时返回 None。
        """
        if not self.allows_start(key, manual) or key in self.checks or self.is_recording(key):
            return None
        token = object()
        self.checks[key] = token
        return token

    def end_check(self, key, token):
        """释放与当前检查令牌匹配的状态。

        Args:
            key: 由平台标识和房间号组成的元组。
            token: begin_check 返回的检查令牌。
        """
        # 只清理本轮检查持有的令牌，避免旧检查误删后来启动的检查状态。
        if self.checks.get(key) is token:
            self.checks.pop(key, None)
            self.check_tasks.pop(key, None)

    def is_recording(self, key):
        task = self.tasks.get(key)
        return task is not None and not task.done()

    def start_recording(self, key, record, finish, *, token=None, manual=False):
        """注册后台录制任务，并在任务结束时执行清理。

        Args:
            key: 由平台标识和房间号组成的元组。
            record: 无参数的异步录制回调。
            finish: 无参数的异步清理回调，录制失败或取消时也会调用。
            token: 可选检查令牌；提供时必须与当前检查匹配。
            manual: 是否由用户手动启动录制。

        Returns:
            成功注册任务时为 True；启动条件不满足时为 False。
        """
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
                    logger.warning("磁盘保护阻止录制 platform=%s room_id=%s: %s", *key, exc, extra={"event_code": "disk_space"})
                else:
                    logger.exception("录制任务异常 platform=%s room_id=%s", *key)
            except Exception as exc:
                from app.modules.recording.health import RecordingHealthError

                if isinstance(exc, RecordingHealthError):
                    self.notices[key] = {"state": "health_failed", "message": str(exc), "monitor_enabled": False}
                    logger.warning("健康检测停止录制 platform=%s room_id=%s: %s", *key, exc, extra={"event_code": "recording_health"})
                else:
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
            # 完成回调可能晚于下一轮启动，只移除仍指向当前任务的记录。
            if self.tasks.get(key) is completed:
                self.tasks.pop(key, None)
                self.phases.pop(key, None)
            if not completed.cancelled():
                completed.exception()

        task.add_done_callback(done)
        return True

    async def stop_room(self, key, *, reason=None, message=None):
        """取消并等待指定直播间的检查和录制任务结束。

        Args:
            key: 由平台标识和房间号组成的元组。
            reason: 可选停止状态码，用于保留停止原因。
            message: 与停止状态一起展示的说明。
        """
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
        """返回以数据库直播间 ID 为键的检查、录制和停止状态快照。"""
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
        """解除全局暂停；应用已进入关闭流程时返回 False。"""
        if self.closing:
            return False
        self.paused = False
        return True

    async def stop_all(self):
        """暂停自动录制，取消并回收所有检查、录制任务及输出路径占用。"""
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
        """禁止后续启动，并等待所有检查和录制任务结束。"""
        self.closing = True
        await self.stop_all()


def get_recording_tasks(app):
    """获取应用的录制任务管理器，不存在时创建并挂载到 app.state。

    Args:
        app: 保存录制任务管理器的应用实例。

    Returns:
        当前应用共用的 RecordingTaskManager 实例。
    """
    manager = getattr(app.state, "recording_tasks", None)
    if manager is None:
        manager = RecordingTaskManager()
        app.state.recording_tasks = manager
    return manager
