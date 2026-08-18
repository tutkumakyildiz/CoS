"""Sanity tests for the task_store tool against a throwaway sqlite db.

Run with: pytest (after `pip install -e .[dev]`)
"""

from __future__ import annotations

import tempfile
from datetime import date, timedelta
from pathlib import Path

import pytest

from cos.db import init_db
from cos.tools.task_store import build_task_store_tools


@pytest.fixture()
def tools():
    with tempfile.TemporaryDirectory() as tmp:
        init_db(Path(tmp) / "test.db")
        ts = {t.tool_name: t for t in build_task_store_tools("chat-1")}
        yield ts


def _call(tool, **kwargs):
    # DecoratedFunctionTool is directly callable like the plain function it wraps.
    return tool(**kwargs)


def test_create_and_get_open_tasks(tools):
    task = _call(tools["create_task"], title="Buy soccer shoes", category="errand", created_by="111")
    assert task["status"] == "open"
    assert task["chat_id"] == "chat-1"

    open_tasks = _call(tools["get_open_tasks"])
    assert [t["task_id"] for t in open_tasks] == [task["task_id"]]


def test_update_task_owner(tools):
    task = _call(tools["create_task"], title="Renew passport", category="admin", created_by="111")
    updated = _call(tools["update_task"], task_id=task["task_id"], fields={"owner": "222"})
    assert updated["owner"] == "222"


def test_mark_done_removes_from_open(tools):
    task = _call(tools["create_task"], title="Book dentist", category="appointment", created_by="111")
    _call(tools["mark_done"], task_id=task["task_id"])
    assert _call(tools["get_open_tasks"]) == []


def test_overdue_tasks(tools):
    _call(
        tools["create_task"],
        title="Pay HOA fee",
        category="admin",
        created_by="111",
        due_date="2000-01-01",
    )
    overdue = _call(tools["get_overdue_tasks"])
    assert len(overdue) == 1
    assert overdue[0]["title"] == "Pay HOA fee"


def test_invalid_category_rejected(tools):
    with pytest.raises(ValueError):
        _call(tools["create_task"], title="x", category="not-a-category", created_by="111")


def test_due_soon_excludes_overdue_and_far_future(tools):
    today = date.today()
    _call(
        tools["create_task"],
        title="Overdue task",
        category="admin",
        created_by="111",
        due_date=(today - timedelta(days=1)).isoformat(),
    )
    _call(
        tools["create_task"],
        title="Due tomorrow",
        category="errand",
        created_by="111",
        due_date=(today + timedelta(days=1)).isoformat(),
    )
    _call(
        tools["create_task"],
        title="Due way later",
        category="errand",
        created_by="111",
        due_date=(today + timedelta(days=30)).isoformat(),
    )
    _call(
        tools["create_task"],
        title="No due date",
        category="errand",
        created_by="111",
    )

    due_soon = _call(tools["get_due_soon_tasks"], days=2)
    assert [t["title"] for t in due_soon] == ["Due tomorrow"]


def test_due_soon_includes_today_and_horizon_boundary(tools):
    today = date.today()
    _call(
        tools["create_task"],
        title="Due today",
        category="errand",
        created_by="111",
        due_date=today.isoformat(),
    )
    _call(
        tools["create_task"],
        title="Due right at horizon",
        category="errand",
        created_by="111",
        due_date=(today + timedelta(days=2)).isoformat(),
    )

    due_soon = _call(tools["get_due_soon_tasks"], days=2)
    assert {t["title"] for t in due_soon} == {"Due today", "Due right at horizon"}


def test_due_soon_excludes_done_tasks(tools):
    today = date.today()
    task = _call(
        tools["create_task"],
        title="Return library books",
        category="errand",
        created_by="111",
        due_date=(today + timedelta(days=1)).isoformat(),
    )
    _call(tools["mark_done"], task_id=task["task_id"])

    assert _call(tools["get_due_soon_tasks"], days=2) == []
