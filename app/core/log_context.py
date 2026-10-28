from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps


FIELDS = ("room_id", "platform", "platform_room_id", "recording_log_id", "processing_job_id")
_context = ContextVar("runtime_log_context", default={})


def current_log_context():
    return _context.get()


@contextmanager
def log_context(**fields):
    token = _context.set({**_context.get(), **{key: value for key, value in fields.items() if key in FIELDS and value is not None}})
    try:
        yield
    finally:
        _context.reset(token)


def room_log_fields(room):
    return {"room_id": room.get("id"), "platform": room.get("platform"), "platform_room_id": str(room.get("room_id", ""))}


def recording_log_context(function):
    @wraps(function)
    async def wrapped(self, *args, **kwargs):
        with log_context(**room_log_fields(self.room), recording_log_id=getattr(self, "_log_id", None)):
            return await function(self, *args, **kwargs)
    return wrapped


def processing_log_context(function):
    @wraps(function)
    async def wrapped(self, job, *args, **kwargs):
        with log_context(processing_job_id=job["id"]):
            return await function(self, job, *args, **kwargs)
    return wrapped
