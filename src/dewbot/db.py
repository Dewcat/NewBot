from __future__ import annotations

import contextlib
import sqlite3
import threading
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

from .schema import MIGRATIONS


_JOURNAL_MODE_LOCK = threading.Lock()


class Database:
    """Small SQLite unit-of-work wrapper.

    Definitions and battle runtime state live in the same database but in
    separate tables. Every public write in the engine uses ``transaction`` so
    one skill either resolves completely or rolls back completely.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path) if str(path) != ":memory:" else Path(":memory:")
        self._memory_uri: str | None = None
        self._memory_keeper: sqlite3.Connection | None = None
        if str(self.path) == ":memory:":
            # Separate sqlite3 connections normally receive separate ``:memory:``
            # databases. A named shared-cache URI plus one keeper connection
            # preserves the unit-of-work API used by transactions and reads.
            self._memory_uri = (
                f"file:dewbot-{uuid.uuid4().hex}?mode=memory&cache=shared"
            )
            self._memory_keeper = sqlite3.connect(
                self._memory_uri, uri=True, timeout=30, check_same_thread=False
            )
            self._configure(self._memory_keeper, use_wal=False)

    def connect(self) -> sqlite3.Connection:
        is_memory = self._memory_uri is not None
        if not is_memory:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            self._memory_uri if is_memory else str(self.path),
            timeout=30,
            uri=is_memory,
        )
        self._configure(connection, use_wal=not is_memory)
        return connection

    @staticmethod
    def _configure(connection: sqlite3.Connection, *, use_wal: bool) -> None:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        if use_wal:
            # Changing journal mode itself takes a database lock and does not
            # consistently honor busy_timeout on all SQLite builds. Serialize
            # local workers and retry briefly for concurrent processes.
            with _JOURNAL_MODE_LOCK:
                for attempt in range(20):
                    try:
                        current = str(
                            connection.execute("PRAGMA journal_mode").fetchone()[0]
                        ).lower()
                        if current != "wal":
                            connection.execute("PRAGMA journal_mode = WAL")
                        break
                    except sqlite3.OperationalError as exc:
                        if "locked" not in str(exc).lower() or attempt == 19:
                            raise
                        time.sleep(0.025 * (attempt + 1))

    def close(self) -> None:
        if self._memory_keeper is not None:
            self._memory_keeper.close()
            self._memory_keeper = None

    @contextlib.contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextlib.contextmanager
    def reading(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        connection = self.connect()
        try:
            # Table-rebuild migrations preserve primary keys while replacing
            # parent tables. SQLite requires FK enforcement to be disabled on
            # this migration connection before its transaction begins; the
            # exclusive writer lock prevents concurrent mutations, and a full
            # foreign_key_check runs before commit.
            connection.execute("PRAGMA foreign_keys = OFF")
            # Acquire the writer lock *before* reading migration state. This
            # makes concurrent bot workers serialize the complete
            # check/apply/record sequence instead of all observing an empty
            # schema and racing to CREATE the same tables.
            connection.execute("BEGIN EXCLUSIVE")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            applied = {
                row["version"]
                for row in connection.execute(
                    "SELECT version FROM schema_migrations"
                ).fetchall()
            }
            for version, name, sql in MIGRATIONS:
                if version in applied:
                    continue
                for statement in self._sql_statements(sql):
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_migrations(version,name) VALUES(?,?)",
                    (version, name),
                )
            violations = connection.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise sqlite3.IntegrityError(
                    f"迁移后外键检查失败：{[tuple(row) for row in violations[:10]]}"
                )
            connection.commit()
            connection.execute("PRAGMA foreign_keys = ON")
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _sql_statements(script: str) -> Iterator[str]:
        buffer = ""
        for line in script.splitlines(keepends=True):
            buffer += line
            if sqlite3.complete_statement(buffer):
                statement = buffer.strip()
                if statement:
                    yield statement
                buffer = ""
        if buffer.strip():
            raise sqlite3.OperationalError("迁移脚本包含未结束的 SQL 语句")

    def fetch_one(self, sql: str, params: tuple[object, ...] = ()) -> sqlite3.Row | None:
        with self.reading() as connection:
            return connection.execute(sql, params).fetchone()

    def fetch_all(self, sql: str, params: tuple[object, ...] = ()) -> list[sqlite3.Row]:
        with self.reading() as connection:
            return connection.execute(sql, params).fetchall()
