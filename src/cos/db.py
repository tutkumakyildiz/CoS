"""SQLite persistence — the local/dev backend (see README "Design decisions
worth knowing"); the deployed path uses DynamoDB instead (see
persistence/dynamodb_backend.py).
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id         TEXT PRIMARY KEY,
    chat_id         TEXT NOT NULL,
    title           TEXT NOT NULL,
    category        TEXT NOT NULL CHECK (category IN
                        ('errand','admin','gift','appointment','recurring','other')),
    created_by      TEXT NOT NULL,
    owner           TEXT,
    due_date        TEXT,
    status          TEXT NOT NULL CHECK (status IN
                        ('open','in_progress','done','snoozed')) DEFAULT 'open',
    recurrence      TEXT,
    source_message  TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    last_nudge_at   TEXT,
    completed_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_chat_status ON tasks (chat_id, status);
CREATE INDEX IF NOT EXISTS idx_tasks_chat_owner ON tasks (chat_id, owner);
"""

_connection: sqlite3.Connection | None = None


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns that postdate a database file's original creation.

    `CREATE TABLE IF NOT EXISTS` in SCHEMA only helps brand-new databases —
    an existing `data/cos.db` from before `completed_at` was added needs the
    column added explicitly, or metrics queries against it will fail.
    """
    existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)")}
    if "completed_at" not in existing_cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN completed_at TEXT")
        # Backfill: tasks already marked done before this column existed have
        # no real completion timestamp on record, but the convention (spec
        # §8: never touch a task after marking it done) means updated_at on
        # a done row is effectively its completion time — a fine one-time
        # substitute so pre-existing completions aren't invisible to metrics.
        conn.execute("UPDATE tasks SET completed_at = updated_at WHERE status = 'done' AND completed_at IS NULL")
        conn.commit()


def init_db(db_path: Path) -> sqlite3.Connection:
    """Open (creating if needed) the sqlite file and ensure schema exists.

    Call once at process startup; reuse the returned connection (or call
    `get_connection()` from tool code) rather than opening a new one per call.
    """
    global _connection
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    conn.commit()
    _migrate(conn)
    _connection = conn
    return conn


def get_connection() -> sqlite3.Connection:
    if _connection is None:
        raise RuntimeError("Database not initialized — call init_db(settings.db_path) at startup first.")
    return _connection


@contextmanager
def cursor():
    conn = get_connection()
    cur = conn.cursor()
    try:
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
