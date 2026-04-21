from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Iterator

from app.db.schema import SCHEMA_SQL


class Database:
    def __init__(self, path: str) -> None:
        self.path = self._resolve_path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = RLock()
        self._initialize()

    def _resolve_path(self, path: str) -> Path:
        configured_path = Path(path)
        if configured_path.is_absolute():
            return configured_path

        runtime_root = Path(__file__).resolve().parents[2]
        if runtime_root.name == "backend":
            runtime_root = runtime_root.parent
        return runtime_root / configured_path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=30,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self.session() as connection:
            connection.executescript(SCHEMA_SQL)

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @property
    def write_lock(self) -> RLock:
        return self._write_lock
