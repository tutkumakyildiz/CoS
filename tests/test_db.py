"""Tests for db.py's schema migration — specifically that an existing sqlite
file created before `completed_at` was added gets the column added in place,
rather than failing (or silently missing it) on the next `init_db` call.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from cos.db import init_db


def test_init_db_adds_completed_at_to_pre_existing_db():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"

        # Simulate a database file created before completed_at existed.
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            CREATE TABLE tasks (
                task_id         TEXT PRIMARY KEY,
                chat_id         TEXT NOT NULL,
                title           TEXT NOT NULL,
                category        TEXT NOT NULL,
                created_by      TEXT NOT NULL,
                owner           TEXT,
                due_date        TEXT,
                status          TEXT NOT NULL DEFAULT 'open',
                recurrence      TEXT,
                source_message  TEXT,
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL,
                last_nudge_at   TEXT
            )
            """
        )
        conn.commit()
        conn.close()

        conn = init_db(db_path)
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)")}
        assert "completed_at" in cols


def test_init_db_backfills_completed_at_for_pre_existing_done_tasks():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"

        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            CREATE TABLE tasks (
                task_id         TEXT PRIMARY KEY,
                chat_id         TEXT NOT NULL,
                title           TEXT NOT NULL,
                category        TEXT NOT NULL,
                created_by      TEXT NOT NULL,
                owner           TEXT,
                due_date        TEXT,
                status          TEXT NOT NULL DEFAULT 'open',
                recurrence      TEXT,
                source_message  TEXT,
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL,
                last_nudge_at   TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO tasks (task_id, chat_id, title, category, created_by, status, created_at, updated_at) "
            "VALUES ('t1', 'chat-1', 'Buy milk', 'errand', '111', 'done', '2026-08-18T10:00:00+00:00', "
            "'2026-08-18T18:45:22+00:00')"
        )
        conn.execute(
            "INSERT INTO tasks (task_id, chat_id, title, category, created_by, status, created_at, updated_at) "
            "VALUES ('t2', 'chat-1', 'Buy eggs', 'errand', '111', 'open', '2026-08-18T10:00:00+00:00', "
            "'2026-08-18T10:00:00+00:00')"
        )
        conn.commit()
        conn.close()

        conn = init_db(db_path)
        rows = {row["task_id"]: row["completed_at"] for row in conn.execute("SELECT task_id, completed_at FROM tasks")}
        assert rows["t1"] == "2026-08-18T18:45:22+00:00"  # backfilled from updated_at
        assert rows["t2"] is None  # still open — nothing to backfill


def test_init_db_is_idempotent_once_migrated():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        init_db(db_path)
        # Calling init_db again against an already-migrated db should not error.
        conn = init_db(db_path)
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)")}
        assert "completed_at" in cols
