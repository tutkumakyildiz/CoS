"""Persistence contract for the `task_store` tools — see design spec §8.

Two implementations: `SqliteTaskStoreBackend` (today's default) and
`DynamoDBTaskStoreBackend` (the hackathon/AgentCore target, since AgentCore's
containers are ephemeral and can't read/write a local SQLite file). Both
return plain dicts/lists shaped exactly like a `tasks` row: same keys, same
types — so `tools/task_store.py`'s `@tool` functions never need to know
which backend is active, only this interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class TaskStoreBackend(ABC):
    @abstractmethod
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
    ) -> dict[str, Any]: ...

    @abstractmethod
    def update_task(self, *, chat_id: str, task_id: str, fields: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    def mark_done(self, *, chat_id: str, task_id: str) -> dict[str, Any]: ...

    @abstractmethod
    def get_open_tasks(self, *, chat_id: str, owner: str | None = None) -> list[dict[str, Any]]: ...

    @abstractmethod
    def get_overdue_tasks(self, *, chat_id: str) -> list[dict[str, Any]]: ...

    @abstractmethod
    def get_due_soon_tasks(self, *, chat_id: str, days: int = 2) -> list[dict[str, Any]]: ...

    @abstractmethod
    def get_weekly_metrics(self, *, chat_id: str, days: int = 7) -> dict[str, Any]: ...


def grouped_pct(counts: dict[str, int], total: int) -> dict[str, float]:
    """Shared by both backends so percentage math isn't duplicated (and can't
    drift) between them — see task_store.py's get_weekly_metrics docstring
    for why this is computed in code rather than left to the model."""
    if total == 0:
        return {}
    return {k: round(100 * v / total, 1) for k, v in counts.items()}
