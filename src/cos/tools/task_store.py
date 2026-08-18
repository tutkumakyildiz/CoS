"""`task_store` tool — spec §4.1.

Implemented as several small single-purpose Strands tools rather than one
dispatch-by-action tool, since that's the more idiomatic shape for a Strands
agent's tool-calling (each action gets its own name + schema) while keeping
the same action set the spec defines.

Each tool is bound to a single `chat_id` at construction time via
`build_task_store_tools`, so the agent can never accidentally read or write
another chat's tasks (spec §8 constraint: "Only act on tasks in this chat's
own task list") — that's enforced in code, not just the prompt.

Backed by SQLite — spec §8 left this open pending a Google Sheets
implementation, but SQLite is the permanent choice for this project
(decided 2026-08-18, see README "Design deviations"), not a placeholder.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from strands import tool

from cos.db import cursor

VALID_CATEGORIES = {"errand", "admin", "gift", "appointment", "recurring", "other"}
VALID_STATUSES = {"open", "in_progress", "done", "snoozed"}
OPEN_STATUSES = ("open", "in_progress")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row) -> dict[str, Any]:
    return dict(row)


def build_task_store_tools(chat_id: str) -> list:
    """Build the task_store tool set, scoped to one chat_id."""

    @tool
    def create_task(
        title: str,
        category: str,
        created_by: str,
        due_date: str | None = None,
        owner: str | None = None,
        recurrence: str | None = None,
        source_message: str | None = None,
    ) -> dict[str, Any]:
        """Create a new task from a captured mention.

        Args:
            title: Short, human-readable task title, e.g. "Buy soccer shoes for Mia".
            category: One of errand, admin, gift, appointment, recurring, other.
            created_by: Telegram user id of whoever's message this was captured from.
            due_date: ISO date (YYYY-MM-DD) if stated or clearly implied. Leave unset
                if no deadline was given — do not invent one.
            owner: Telegram user id of whoever is responsible, if already known/stated.
                Leave unset if ownership hasn't been decided yet.
            recurrence: e.g. "annual:2026-09-01" for season-based reminders. Leave unset
                unless a recurring/seasonal pattern was clearly implied.
            source_message: The original raw message text, for traceability.

        Returns:
            The created task record.
        """
        if category not in VALID_CATEGORIES:
            raise ValueError(f"category must be one of {sorted(VALID_CATEGORIES)}, got {category!r}")

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

    @tool
    def update_task(task_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        """Update one or more fields on an existing task (in this chat only).

        Args:
            task_id: The task's id.
            fields: Partial dict of fields to change. Allowed keys: title, category,
                owner, due_date, status, recurrence, last_nudge_at. status must be one
                of open, in_progress, done, snoozed — never delete a task, use status
                'done' or 'snoozed' instead. Setting status to 'done' this way also
                records completed_at automatically, same as mark_done.

        Returns:
            The updated task record.
        """
        allowed = {"title", "category", "owner", "due_date", "status", "recurrence", "last_nudge_at"}
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"Unknown field(s) for update_task: {sorted(unknown)}. Allowed: {sorted(allowed)}")
        if "category" in fields and fields["category"] not in VALID_CATEGORIES:
            raise ValueError(f"category must be one of {sorted(VALID_CATEGORIES)}")
        if "status" in fields and fields["status"] not in VALID_STATUSES:
            raise ValueError(f"status must be one of {sorted(VALID_STATUSES)}")
        if not fields:
            raise ValueError("fields must not be empty")

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

    @tool
    def mark_done(task_id: str) -> dict[str, Any]:
        """Mark a task done. Use this instead of deleting a task.

        Args:
            task_id: The task's id.
        """
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

    @tool
    def get_open_tasks(owner: str | None = None) -> list[dict[str, Any]]:
        """List open (open or in_progress) tasks in this chat, optionally filtered by owner.

        Args:
            owner: Telegram user id to filter by. Leave unset to get all open tasks.
        """
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

    @tool
    def get_overdue_tasks() -> list[dict[str, Any]]:
        """List tasks in this chat that are open/in_progress and past their due_date."""
        today = date.today().isoformat()
        with cursor() as cur:
            cur.execute(
                "SELECT * FROM tasks WHERE chat_id = ? AND status IN (?, ?) "
                "AND due_date IS NOT NULL AND due_date < ? ORDER BY due_date ASC",
                (chat_id, *OPEN_STATUSES, today),
            )
            rows = cur.fetchall()
        return [_row_to_dict(r) for r in rows]

    @tool
    def get_due_soon_tasks(days: int = 2) -> list[dict[str, Any]]:
        """List open/in_progress tasks in this chat due within the next `days` days
        (today through today+days inclusive). Excludes tasks already overdue —
        use get_overdue_tasks for those — and tasks with no due_date.

        Args:
            days: How many days ahead counts as "due soon". Defaults to 2.
        """
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

    @tool
    def get_weekly_metrics(days: int = 7) -> dict[str, Any]:
        """Basic usage metrics for this chat over the last `days` days, for the
        weekly stats summary — spec §7 "basic metrics logging". Percentages are
        computed here (not left to the model) to avoid arithmetic mistakes.

        Args:
            days: How many days back to look. Defaults to 7 (one week).

        Returns:
            since: ISO date the window starts at.
            captured_total / captured_by_owner / captured_pct_by_owner: tasks
                created in the window, grouped by created_by (who reported it).
            completed_total / completed_by_owner / completed_pct_by_owner: tasks
                completed in the window, grouped by owner (who it was assigned to).
            resolved_without_nudge / resolved_with_nudge / resolved_without_nudge_pct:
                of the tasks completed in the window, how many were closed out
                before CoS ever had to send a reminder for them.
            Owner/created_by keys are telegram user ids — map them to display
            names from the household roster before showing this to anyone.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        since = (date.today() - timedelta(days=days)).isoformat()

        def _grouped_pct(counts: dict[str, int], total: int) -> dict[str, float]:
            if total == 0:
                return {}
            return {k: round(100 * v / total, 1) for k, v in counts.items()}

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
            "captured_pct_by_owner": _grouped_pct(captured_by_owner, captured_total),
            "completed_total": completed_total,
            "completed_by_owner": completed_by_owner,
            "completed_pct_by_owner": _grouped_pct(completed_by_owner, completed_total),
            "resolved_without_nudge": resolved_without_nudge,
            "resolved_with_nudge": resolved_with_nudge,
            "resolved_without_nudge_pct": (
                round(100 * resolved_without_nudge / completed_total, 1) if completed_total else 0.0
            ),
        }

    return [
        create_task,
        update_task,
        mark_done,
        get_open_tasks,
        get_overdue_tasks,
        get_due_soon_tasks,
        get_weekly_metrics,
    ]
