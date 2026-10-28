from collections import deque
from datetime import datetime, timezone
import json
import heapq
from itertools import chain, islice
import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path
from queue import Full, Queue
from threading import Lock, Thread
import time
from uuid import uuid4

from app.core.log_context import FIELDS, current_log_context
from app.modules.observability.redaction import redact


MAX_RECORD_BYTES = 65536
LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}


def reverse_lines(path):
    with path.open("rb") as stream:
        position = stream.seek(0, 2)
        pending = b""
        dropping = False
        while position:
            size = min(position, MAX_RECORD_BYTES)
            position -= size
            stream.seek(position)
            lines = (stream.read(size) + pending).split(b"\n")
            pending = lines.pop(0)
            if dropping and lines:
                lines.pop()
                dropping = False
            for line in reversed(lines):
                if line and len(line) <= MAX_RECORD_BYTES:
                    yield line
            if len(pending) > MAX_RECORD_BYTES:
                pending, dropping = b"", True
        if pending and not dropping:
            yield pending


class RuntimeLogStore:
    def __init__(self, directory, *, max_bytes=10 * 1024 * 1024, backups=5, secrets=()):
        self.directory = Path(directory)
        self.write_error = ""
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            self.handler = RotatingFileHandler(self.directory / "runtime.jsonl", maxBytes=max_bytes, backupCount=backups, encoding="utf-8")
            self.handler.setFormatter(logging.Formatter("%(message)s"))
            self.handler.handleError = self._write_error
        except OSError:
            self.handler = None
            self.write_error = "日志文件不可写，当前仅保留内存日志"
        self.backups, self.max_bytes, self.secrets = backups, max_bytes, secrets
        self.lock = Lock()
        self.recent = deque(maxlen=1000)
        self.queue = Queue(maxsize=2000)
        self.dropped = 0
        self.closed = False
        self.sequence = time.time_ns()
        for event in reversed(list(islice(self._disk_events(), 1000))):
            self.recent.append(event)
            self.sequence = max(self.sequence, int(event["id"].split("-")[0]))
        self.worker = Thread(target=self._write_loop, name="runtime-log-writer", daemon=True)
        self.worker.start()

    def _write_error(self, record):
        self.write_error = "日志文件写入失败，请检查磁盘空间和目录权限"

    def _disk_events(self):
        for number in range(self.backups + 1):
            path = self.directory / ("runtime.jsonl" + (f".{number}" if number else ""))
            try:
                for raw in reverse_lines(path):
                    try:
                        event = json.loads(raw)
                        if (not isinstance(event, dict) or not isinstance(event.get("id"), str)
                                or not re.fullmatch(r"\d{20}-[a-f0-9]{8}", event["id"]) or not isinstance(event.get("message"), str)
                                or not isinstance(event.get("timestamp"), str) or event.get("level") not in LEVELS):
                            continue
                        event["message"] = redact(event["message"], self.secrets)[:8000]
                        event["traceback"] = redact(event.get("traceback", ""), self.secrets)[-16000:]
                        yield {key: value for key, value in event.items() if key in {"id", "timestamp", "level", "logger", "message", "traceback", "event_code", "truncated", *FIELDS}}
                    except (ValueError, UnicodeError):
                        continue
            except OSError:
                continue

    def append(self, record):
        context = {**current_log_context(), **{key: getattr(record, key) for key in FIELDS if getattr(record, key, None) is not None}}
        context = {key: value if isinstance(value, int) else str(value)[:128] for key, value in context.items()}
        trace = logging.Formatter().formatException(record.exc_info) if record.exc_info else record.exc_text or ""
        if record.stack_info:
            trace += "\n" + record.stack_info
        message = redact(record.getMessage(), self.secrets)
        trace = redact(trace, self.secrets)
        event = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname, "logger": record.name[:256],
            "message": message[:8000], "traceback": trace[-16000:],
            "truncated": len(message) > 8000 or len(trace) > 16000,
            "event_code": str(getattr(record, "event_code", "unclassified"))[:64], **context,
        }
        if event["event_code"] == "unclassified" and record.exc_info and record.exc_info[0].__module__.startswith(("sqlalchemy", "sqlite3", "aiosqlite")):
            event["event_code"] = "database"
        while len(json.dumps(event, ensure_ascii=False).encode("utf-8")) > MAX_RECORD_BYTES - 256:
            event["truncated"] = True
            event["traceback"] = event["traceback"][len(event["traceback"]) // 2:]
            event["message"] = event["message"][:len(event["message"]) // 2]
        with self.lock:
            if self.closed:
                return
            self.sequence = max(time.time_ns(), self.sequence + 1)
            event["id"] = f"{self.sequence:020d}-{uuid4().hex[:8]}"
            self.recent.append(event)
            try:
                self.queue.put_nowait(event)
            except Full:
                self.dropped += 1

    def _write_loop(self):
        while True:
            event = self.queue.get()
            try:
                if event is None:
                    return
                record = logging.LogRecord("runtime", logging.INFO, "", 0, json.dumps(event, ensure_ascii=False), (), None)
                if self.handler is not None:
                    self.handler.emit(record)
            except Exception:
                self.write_error = "日志文件写入失败，请检查磁盘空间和目录权限"
            finally:
                self.queue.task_done()

    def query(self, *, room_id=None, platform=None, recording_log_id=None, processing_job_id=None, level=None, keyword=None, start=None, end=None, before=None, after=None, limit=200, minimum_level=None):
        with self.lock:
            recent = list(self.recent)
        # Live polling only needs the bounded memory tail; older cursors fall back to disk.
        if after and recent and after >= recent[0]["id"]:
            candidates = reversed(recent)
        else:
            candidates = chain(reversed(recent), self._disk_events())
        cursor = max([event["id"] for event in recent] + [after or ""], default="")
        def matching():
            seen = set()
            for event in candidates:
                if event["id"] in seen:
                    continue
                seen.add(event["id"])
                if before and event["id"] >= before or after and event["id"] <= after:
                    continue
                if room_id is not None and event.get("room_id") != room_id or platform and event.get("platform") != platform:
                    continue
                if recording_log_id is not None and event.get("recording_log_id") != recording_log_id or processing_job_id and event.get("processing_job_id") != processing_job_id:
                    continue
                if level and event["level"] != level or minimum_level and LEVELS.get(event["level"], 0) < minimum_level:
                    continue
                if start and event["timestamp"] < start or end and event["timestamp"] > end:
                    continue
                if keyword and keyword.casefold() not in (event["message"] + event.get("traceback", "")).casefold():
                    continue
                yield event
        result = heapq.nsmallest(limit + 1, matching(), key=lambda event: event["id"]) if after else list(islice(matching(), limit + 1))
        more = len(result) > limit
        result = sorted(result[:limit], key=lambda event: event["id"], reverse=True)
        if after and more and result:
            cursor = result[0]["id"]
        return {"entries": result, "has_more": more, "next_before": result[-1]["id"] if result else None,
                "cursor": cursor, "dropped": self.dropped, "write_error": self.write_error}

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
        self.queue.put(None)
        self.worker.join()
        if self.handler is not None:
            self.handler.close()
