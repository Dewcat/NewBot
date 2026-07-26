"""Single-frontend runtime lock.

Dewbot supports two interchangeable frontends (the Telegram bot and the web
UI) over the same database. Only one may run at a time: engine mutations are
serialized by an in-process asyncio lock, which two OS processes cannot
share. The lock file lives next to the database file and carries a heartbeat
so a crashed frontend never blocks the next start for long.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any


HEARTBEAT_SECONDS = 15
STALE_AFTER_SECONDS = 60


class FrontendLockError(RuntimeError):
    """Raised when another live frontend already owns the database."""


class FrontendLock:
    def __init__(self, database_path: str | Path, frontend: str):
        self._enabled = str(database_path) != ":memory:"
        self.path = Path(f"{database_path}.frontend.lock")
        self.frontend = frontend
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def acquire(self) -> None:
        if not self._enabled:
            return
        current = self._read()
        if current is not None:
            age = time.time() - float(current.get("heartbeat", 0))
            if age < STALE_AFTER_SECONDS and int(current.get("pid", -1)) != os.getpid():
                raise FrontendLockError(
                    f"另一个前端（{current.get('frontend', '?')}，"
                    f"PID {current.get('pid', '?')}）正在使用该数据库"
                    f"（最近心跳 {int(age)} 秒前）。同一时间只允许运行一个前端；"
                    f"请先停止它，或在其心跳过期（{STALE_AFTER_SECONDS} 秒）后重试。"
                )
        self._write()
        self._thread = threading.Thread(
            target=self._beat, daemon=True, name="dewbot-frontend-lock"
        )
        self._thread.start()

    def release(self) -> None:
        if not self._enabled:
            return
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=HEARTBEAT_SECONDS + 1)
            self._thread = None
        current = self._read()
        if current is not None and int(current.get("pid", -1)) == os.getpid():
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass

    def __enter__(self) -> "FrontendLock":
        self.acquire()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.release()

    def _beat(self) -> None:
        while not self._stop.wait(HEARTBEAT_SECONDS):
            try:
                self._write()
            except OSError:
                pass

    def _read(self) -> dict[str, Any] | None:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _write(self) -> None:
        payload = json.dumps(
            {"frontend": self.frontend, "pid": os.getpid(), "heartbeat": time.time()}
        )
        temp = self.path.with_name(self.path.name + ".tmp")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp.write_text(payload, encoding="utf-8")
        os.replace(temp, self.path)


__all__ = ["FrontendLock", "FrontendLockError", "HEARTBEAT_SECONDS", "STALE_AFTER_SECONDS"]
