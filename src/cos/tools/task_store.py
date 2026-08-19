"""`task_store` tool — spec §4.1.

Implemented as several small single-purpose Strands tools rather than one
dispatch-by-action tool, since that's the more idiomatic shape for a Strands
agent's tool-calling (each action gets its own name + schema) while keeping
the same action set the spec defines.

Each tool is bound to a single `chat_id` at construction time via
`build_task_store_tools`, so the agent can never accidentally read or write
another chat's tasks (spec §8 constraint: "Only act on tasks in this chat's
own task list") — that's enforced in code, not just the prompt.

Persistence lives behind `cos.persistence.TaskStoreBackend` (design spec §8)
— SQLite by default (today), swappable to DynamoDB for the hackathon/
AgentCore target via `COS_PERSISTENCE_BACKEND`. These tool functions only
validate input and shape the response; they never touch SQL or DynamoDB
directly.
"""

from __future__ import annotations

from typing import Any

from strands import tool

from cos.persistence.base import TaskStoreBackend
from cos.persistence.sqlite_backend import SqliteTaskStoreBackend

VALID_CATEGORIES = {"errand", "admin", "gift", "appointment", "recurring", "other"}
VALID_STATUSES = {"open", "in_progress", "done", "snoozed"}


def build_task_store_tools(chat_id: str, backend: TaskStoreBackend | None = None) -> list:
    """Build the task_store tool set, scoped to one chat_id.

    Args:
        chat_id: The chat this tool set is scoped to (enforced here, not just
            in the prompt — spec §8 constraint).
        backend: Persistence backend to use. Defaults to a fresh SQLite
            backend (today's behavior) if not given — pass a DynamoDB
            backend (via `cos.persistence.get_backend`) for the hackathon/
            AgentCore path.
    """
    backend = backend or SqliteTaskStoreBackend()

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

        return backend.create_task(
            chat_id=chat_id,
            title=title,
            category=category,
            created_by=created_by,
            due_date=due_date,
            owner=owner,
            recurrence=recurrence,
            source_message=source_message,
        )

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

        return backend.update_task(chat_id=chat_id, task_id=task_id, fields=fields)

    @tool
    def mark_done(task_id: str) -> dict[str, Any]:
        """Mark a task done. Use this instead of deleting a task.

        Args:
            task_id: The task's id.
        """
        return backend.mark_done(chat_id=chat_id, task_id=task_id)

    @tool
    def get_open_tasks(owner: str | None = None) -> list[dict[str, Any]]:
        """List open (open or in_progress) tasks in this chat, optionally filtered by owner.

        Args:
            owner: Telegram user id to filter by. Leave unset to get all open tasks.
        """
        return backend.get_open_tasks(chat_id=chat_id, owner=owner)

    @tool
    def get_overdue_tasks() -> list[dict[str, Any]]:
        """List tasks in this chat that are open/in_progress and past their due_date."""
        return backend.get_overdue_tasks(chat_id=chat_id)

    @tool
    def get_due_soon_tasks(days: int = 2) -> list[dict[str, Any]]:
        """List open/in_progress tasks in this chat due within the next `days` days
        (today through today+days inclusive). Excludes tasks already overdue —
        use get_overdue_tasks for those — and tasks with no due_date.

        Args:
            days: How many days ahead counts as "due soon". Defaults to 2.
        """
        return backend.get_due_soon_tasks(chat_id=chat_id, days=days)

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
        return backend.get_weekly_metrics(chat_id=chat_id, days=days)

    return [
        create_task,
        update_task,
        mark_done,
        get_open_tasks,
        get_overdue_tasks,
        get_due_soon_tasks,
        get_weekly_metrics,
    ]
