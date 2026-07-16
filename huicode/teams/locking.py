from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

from .types import TeamError


class FileLock:
    def __init__(self, path: Path, *, retries: int = 8, retry_ms: int = 50, stale_seconds: int = 30) -> None:
        self.path = path
        self.retries = retries
        self.retry_ms = retry_ms
        self.stale_seconds = stale_seconds
        self.token = uuid.uuid4().hex
        self.acquired = False

    def __enter__(self) -> "FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(self.retries + 1):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                payload = json.dumps({"pid": os.getpid(), "created_at": time.time(), "token": self.token})
                os.write(fd, payload.encode("utf-8"))
                os.close(fd)
                self.acquired = True
                return self
            except FileExistsError:
                if self._is_stale():
                    try:
                        self.path.unlink()
                    except OSError:
                        pass
                    continue
                if attempt < self.retries:
                    time.sleep(self.retry_ms / 1000)
        raise TeamError("lock_timeout", f"无法获取团队文件锁: {self.path.name}")

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        if not self.acquired:
            return
        try:
            current = json.loads(self.path.read_text(encoding="utf-8"))
            if current.get("token") == self.token:
                self.path.unlink(missing_ok=True)
        except (OSError, ValueError, TypeError):
            pass
        self.acquired = False

    def _is_stale(self) -> bool:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            created = float(data.get("created_at", 0))
            pid = int(data.get("pid", 0))
        except (OSError, ValueError, TypeError):
            return False
        if time.time() - created <= self.stale_seconds:
            return False
        return not _pid_alive(pid)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True
