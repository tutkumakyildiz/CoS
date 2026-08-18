"""SQLite persistence — spec §3/§8 called for Google Sheets, but SQLite is
the permanent choice for this project (decided 2026-08-18, see README
"Design deviations"), not a temporary stand-in.
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
    last_nudge_at   TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_chat_status ON tasks (chat_id, status);
CREATE INDEX IF NOT EXISTS idx_tasks_chat_owner ON tasks (chat_id, owner);

CREATE TABLE IF NOT EXISTS digest_log (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    week_of              TEXT NOT NULL,
    chat_id              TEXT NOT NULL,
    open_count_by_owner  TEXT NOT NULL,  -- JSON
    sent_at              TEXT NOT NULL
);
"""

_connection: sqlite3.Connection | None = None


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
