import os
from pathlib import Path

from sqlalchemy.engine import make_url

from app.core.config import ROOT_DIR


class InstanceLock:
    def __init__(self, database_url):
        url = make_url(database_url)
        if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
            path = Path(url.database).resolve()
            self.path = path.with_name(path.name + ".lock")
        else:
            self.path = ROOT_DIR / "data" / "recorder.lock"
        self.file = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        if self.path.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise RuntimeError("已有后端使用该数据库，请只运行一个后端进程（workers=1）") from exc
        self.file = handle

    def release(self):
        if self.file is not None:
            self.file.close()
            self.file = None
