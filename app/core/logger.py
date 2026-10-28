import copy
import logging
import sys
from app.core.config import local_config
from app.core.paths import ROOT_DIR
from app.modules.observability.logs import RuntimeLogStore
from app.modules.observability.redaction import configured_secrets, redact


_store = None
_secrets = configured_secrets(local_config)


class SanitizedFormatter(logging.Formatter):
    def format(self, record):
        safe = copy.copy(record)
        safe.msg, safe.args = redact(record.getMessage(), _secrets), ()
        safe.exc_text = redact(self.formatException(record.exc_info), _secrets) if record.exc_info else redact(record.exc_text or "", _secrets) or None
        safe.exc_info = None
        safe.stack_info = redact(record.stack_info, _secrets) if record.stack_info else None
        return super().format(safe)


class RuntimeLogHandler(logging.Handler):
    def emit(self, record):
        store = _store
        if store is not None and (record.name.startswith("app.") or record.name == "uvicorn.error" or record.levelno >= logging.WARNING):
            if record.name != "uvicorn.access":
                try:
                    store.append(record)
                except Exception:
                    store.dropped += 1


def setup_logging():
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
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        for handler in logger.handlers:
            handler.setFormatter(formatter)
        if not logger.propagate and not any(isinstance(handler, RuntimeLogHandler) for handler in logger.handlers):
            logger.addHandler(RuntimeLogHandler())
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
        _store = RuntimeLogStore(directory or ROOT_DIR / "logs", secrets=_secrets,
                                 max_bytes=bounded(config.get("max_file_mb"), 10, 100) * 1024 * 1024,
                                 backups=bounded(config.get("backups"), 5, 10))
    return _store


def stop_runtime_logging():
    global _store
    store, _store = _store, None
    if store is not None:
        store.close()


def get_logger(name: str):
    return logging.getLogger(name)
