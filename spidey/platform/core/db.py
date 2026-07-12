"""SQLite storage with a versioned migration runner.

One file at ``~/.spidey/platform.db`` (override with $SPIDEY_DB). Every access
opens a short-lived WAL-mode connection with a busy timeout, so the queue
workers, the scheduler and request handlers can all touch the database from
their own threads without stepping on each other.

Migrations live in :mod:`.migrations` as numbered SQL blocks; applied versions
are recorded in ``schema_migrations`` so upgrades are idempotent — the same
model as Alembic/Flyway, sized for SQLite.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, List, Optional

_init_lock = threading.Lock()
_initialized_for: Optional[str] = None


def db_path() -> Path:
    p = os.environ.get("SPIDEY_DB")
    if p:
        return Path(p)
    return Path.home() / ".spidey" / "platform.db"


def data_dir() -> Path:
    """Where the platform stores uploaded/processed artifacts."""
    d = os.environ.get("SPIDEY_PLATFORM_HOME")
    root = Path(d) if d else Path.home() / ".spidey" / "platform"
    root.mkdir(parents=True, exist_ok=True)
    return root


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    init()
    conn = sqlite3.connect(db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def query(sql: str, params: tuple = ()) -> List[dict]:
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def one(sql: str, params: tuple = ()) -> Optional[dict]:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: tuple = ()) -> int:
    """Run a statement; returns lastrowid (or rowcount for UPDATE/DELETE)."""
    with connect() as conn:
        cur = conn.execute(sql, params)
        return cur.lastrowid if cur.lastrowid else cur.rowcount


def init() -> None:
    """Create the file and apply any pending migrations (idempotent, thread-safe)."""
    global _initialized_for
    target = str(db_path())
    if _initialized_for == target:
        return
    with _init_lock:
        if _initialized_for == target:
            return
        from .migrations import MIGRATIONS

        db_path().parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(target, timeout=10)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations("
                         "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
            applied = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
            for version, sql in MIGRATIONS:
                if version in applied:
                    continue
                conn.executescript(sql)
                conn.execute("INSERT INTO schema_migrations(version, applied_at) VALUES(?,?)",
                             (version, now()))
                conn.commit()
        finally:
            conn.close()
        _initialized_for = target


def reset_for_tests() -> None:
    """Forget the init cache so tests can point $SPIDEY_DB at a fresh file."""
    global _initialized_for
    _initialized_for = None


def json_dumps(obj: Any) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False, default=str)


def json_loads(text: Optional[str], default: Any = None) -> Any:
    import json
    if not text:
        return default
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return default
