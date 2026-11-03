"""配置日志输出、敏感信息脱敏及运行日志采集的生命周期。"""


import copy
import logging
from logging.handlers import RotatingFileHandler
import sys
from app.core.config import local_config
from app.core.paths import ROOT_DIR
from app.modules.observability.logs import RuntimeLogStore
from app.modules.observability.redaction import configured_secrets, redact


_store = None
_secrets = set()


def refresh_secrets():
    global _secrets
    _secrets = configured_secrets(local_config) | set(_secrets)
    return _secrets


refresh_secrets()


class SanitizedFormatter(logging.Formatter):
    def format(self, record):
        secrets = refresh_secrets()
        safe = copy.copy(record)
        safe.msg, safe.args = redact(record.getMessage(), secrets), ()
        safe.exc_text = redact(self.formatException(record.exc_info), secrets) if record.exc_info else redact(record.exc_text or "", secrets) or None
        safe.exc_info = None
        safe.stack_info = redact(record.stack_info, secrets) if record.stack_info else None
        return super().format(safe)


class RuntimeLogHandler(logging.Handler):
    def emit(self, record):
        refresh_secrets()
        store = _store
        if store is not None and (record.name == "app" or record.name.startswith("app.") or record.name == "uvicorn.error" or record.levelno >= logging.WARNING):
            if record.name != "uvicorn.access":
                try:
                    store.append(record)
                except Exception:
                    store.dropped += 1


def setup_logging():
    refresh_secrets()
    config = local_config.get("logging", {})
    root = logging.getLogger()
    level = getattr(logging, str(config.get("level", "INFO")).upper(), logging.INFO)
    root.setLevel(level if isinstance(level, int) else logging.INFO)
    formatter = SanitizedFormatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    if not any(getattr(handler, "_live_recorder_console", False) for handler in root.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler._live_recorder_console = True
        handler.setFormatter(formatter)
        root.addHandler(handler)
    if not any(isinstance(handler, RuntimeLogHandler) for handler in root.handlers):
        root.addHandler(RuntimeLogHandler())
    for name in ("uvicorn", "uvicorn.error"):
        logger = logging.getLogger(name)
        for handler in logger.handlers:
            handler.setFormatter(formatter)
        if not logger.propagate and not any(isinstance(handler, RuntimeLogHandler) for handler in logger.handlers):
            logger.addHandler(RuntimeLogHandler())
    access_logger = logging.getLogger("uvicorn.access")
    # 访问日志独立落盘，不再传播到 Uvicorn 或根日志的控制台处理器。
    access_logger.propagate = False
    access_logger.setLevel(root.level)
    for handler in list(access_logger.handlers):
        if not getattr(handler, "_live_recorder_access", False):
            access_logger.removeHandler(handler)
    if not access_logger.handlers:
        access_logger.addHandler(logging.NullHandler())
    for name in config.get("quiet_loggers", ["httpx", "httpcore"]):
        logging.getLogger(name).setLevel(logging.WARNING)


def start_runtime_logging(directory=None):
    global _store
    setup_logging()
    if _store is None or _store.closed:
        config = local_config.get("logging", {})
        def bounded(value, default, upper):
            try:
                return max(1, min(upper, int(value)))
            except (TypeError, ValueError):
                return default
        refresh_secrets()
        max_bytes = bounded(config.get("max_file_mb"), 10, 100) * 1024 * 1024
        backups = bounded(config.get("backups"), 5, 10)
        _store = RuntimeLogStore(directory or ROOT_DIR / "logs", secrets=_secrets,
                                 max_bytes=max_bytes, backups=backups)
        _start_access_logging(_store.directory, max_bytes, backups)
    return _store


def _start_access_logging(directory, max_bytes, backups):
    """为 HTTP 访问日志创建独立文件，沿用运行日志的轮转限制。

    Args:
        directory: 日志保存目录。
        max_bytes: 单个文件的轮转阈值，单位为字节。
        backups: 保留的历史文件数量。
    """
    _stop_access_logging()
    access_logger = logging.getLogger("uvicorn.access")
    try:
        directory.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(directory / "access.log", maxBytes=max_bytes,
                                      backupCount=backups, encoding="utf-8")
    except OSError:
        logging.getLogger(__name__).exception("无法创建 HTTP 访问日志文件")
        return
    handler._live_recorder_access = True
    handler.setFormatter(SanitizedFormatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    for previous in list(access_logger.handlers):
        access_logger.removeHandler(previous)
    access_logger.addHandler(handler)


def _stop_access_logging():
    """移除并关闭访问日志文件处理器，允许服务再次启动。"""
    access_logger = logging.getLogger("uvicorn.access")
    for handler in list(access_logger.handlers):
        if getattr(handler, "_live_recorder_access", False):
            access_logger.removeHandler(handler)
            handler.close()
    if not access_logger.handlers:
        access_logger.addHandler(logging.NullHandler())


def stop_runtime_logging():
    global _store
    store, _store = _store, None
    _stop_access_logging()
    if store is not None:
        store.close()


def get_logger(name: str):
    return logging.getLogger(name)
