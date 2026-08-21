"""SQLite implementation of TaskStoreBackend — the local/dev persistence.

Moved here unchanged from task_store.py during the backend-abstraction
refactor: same SQL, same behavior, just behind the TaskStoreBackend
interface so task_store.py's tools don't touch SQL directly.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from cos.db import cursor
from cos.persistence.base import TaskStoreBackend, grouped_pct

OPEN_STATUSES = ("open", "in_progress")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: Any) -> dict[str, Any]:
    return dict(row)


class SqliteTaskStoreBackend(TaskStoreBackend):
    def create_task(
        self,
        *,
        chat_id: str,
        title: str,
        category: str,
        created_by: str,
        due_date: str | None = None,
        owner: str | None = None,
        recurrence: str | None = None,
        source_message: str | None = None,
    ) -> dict[str, Any]:
        task_id = str(uuid.uuid4())
        now = _now()
        with cursor() as cur:
            cur.execute(
                """
                INSERT INTO tasks (
                    task_id, chat_id, title, category, created_by, owner,
                    due_date, status, recurrence, source_message,
                    created_at, updated_at, last_nudge_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, NULL)
                """,
                (task_id, chat_id, title, category, created_by, owner, due_date, recurrence, source_message, now, now),
            )
            cur.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
            row = cur.fetchone()
        return _row_to_dict(row)

    def update_task(self, *, chat_id: str, task_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        if fields.get("status") == "done":
            fields = {**fields, "completed_at": now}

        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [now, task_id, chat_id]
        with cursor() as cur:
            cur.execute(
                f"UPDATE tasks SET {set_clause}, updated_at = ? WHERE task_id = ? AND chat_id = ?",
                values,
            )
            if cur.rowcount == 0:
                raise ValueError(f"No task {task_id} found in this chat")
            cur.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
            row = cur.fetchone()
        return _row_to_dict(row)

    def mark_done(self, *, chat_id: str, task_id: str) -> dict[str, Any]:
        now = _now()
        with cursor() as cur:
            cur.execute(
                "UPDATE tasks SET status = 'done', updated_at = ?, completed_at = ? "
                "WHERE task_id = ? AND chat_id = ?",
                (now, now, task_id, chat_id),
            )
            if cur.rowcount == 0:
                raise ValueError(f"No task {task_id} found in this chat")
            cur.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
            row = cur.fetchone()
        return _row_to_dict(row)

    def get_open_tasks(self, *, chat_id: str, owner: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM tasks WHERE chat_id = ? AND status IN (?, ?)"
        params: list[Any] = [chat_id, *OPEN_STATUSES]
        if owner is not None:
            query += " AND owner = ?"
            params.append(owner)
        query += " ORDER BY due_date IS NULL, due_date ASC, created_at ASC"
        with cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_overdue_tasks(self, *, chat_id: str) -> list[dict[str, Any]]:
        today = date.today().isoformat()
        with cursor() as cur:
            cur.execute(
                "SELECT * FROM tasks WHERE chat_id = ? AND status IN (?, ?) "
                "AND due_date IS NOT NULL AND due_date < ? ORDER BY due_date ASC",
                (chat_id, *OPEN_STATUSES, today),
            )
            rows = cur.fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_due_soon_tasks(self, *, chat_id: str, days: int = 2) -> list[dict[str, Any]]:
        today = date.today()
        today_iso = today.isoformat()
        horizon_iso = (today + timedelta(days=days)).isoformat()
        with cursor() as cur:
            cur.execute(
                "SELECT * FROM tasks WHERE chat_id = ? AND status IN (?, ?) "
                "AND due_date IS NOT NULL AND due_date >= ? AND due_date <= ? ORDER BY due_date ASC",
                (chat_id, *OPEN_STATUSES, today_iso, horizon_iso),
            )
            rows = cur.fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_all_tasks(self, *, chat_id: str) -> list[dict[str, Any]]:
        with cursor() as cur:
            cur.execute(
                "SELECT * FROM tasks WHERE chat_id = ? ORDER BY created_at DESC",
                (chat_id,),
            )
            rows = cur.fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_weekly_metrics(self, *, chat_id: str, days: int = 7) -> dict[str, Any]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        since = (date.today() - timedelta(days=days)).isoformat()

        with cursor() as cur:
            cur.execute(
                "SELECT created_by, COUNT(*) AS n FROM tasks "
                "WHERE chat_id = ? AND created_at >= ? GROUP BY created_by",
                (chat_id, cutoff),
            )
            captured_by_owner = {row["created_by"]: row["n"] for row in cur.fetchall()}

            cur.execute(
                "SELECT owner, COUNT(*) AS n FROM tasks "
                "WHERE chat_id = ? AND status = 'done' AND completed_at >= ? "
                "GROUP BY owner",
                (chat_id, cutoff),
            )
            completed_by_owner = {(row["owner"] or "unassigned"): row["n"] for row in cur.fetchall()}

            cur.execute(
                "SELECT last_nudge_at FROM tasks "
                "WHERE chat_id = ? AND status = 'done' AND completed_at >= ?",
                (chat_id, cutoff),
            )
            nudge_flags = [row["last_nudge_at"] for row in cur.fetchall()]

        captured_total = sum(captured_by_owner.values())
        completed_total = sum(completed_by_owner.values())
        resolved_without_nudge = sum(1 for flag in nudge_flags if flag is None)
        resolved_with_nudge = len(nudge_flags) - resolved_without_nudge

        return {
            "since": since,
            "captured_total": captured_total,
            "captured_by_owner": captured_by_owner,
            "captured_pct_by_owner": grouped_pct(captured_by_owner, captured_total),
            "completed_total": completed_total,
            "completed_by_owner": completed_by_owner,
            "completed_pct_by_owner": grouped_pct(completed_by_owner, completed_total),
            "resolved_without_nudge": resolved_without_nudge,
            "resolved_with_nudge": resolved_with_nudge,
            "resolved_without_nudge_pct": (
                round(100 * resolved_without_nudge / completed_total, 1) if completed_total else 0.0
            ),
        }
