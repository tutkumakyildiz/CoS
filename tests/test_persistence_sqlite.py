"""Tests for SqliteTaskStoreBackend's get_all_tasks — the one backend method
not exposed as an agent @tool (see test_task_store.py for the tool-layer
coverage of everything else). Mirrors test_persistence_dynamodb.py's
get_all_tasks coverage so both backends stay held to the same contract.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from cos.db import init_db
from cos.persistence.sqlite_backend import SqliteTaskStoreBackend


@pytest.fixture()
def backend():
    with tempfile.TemporaryDirectory() as tmp:
        init_db(Path(tmp) / "test.db")
        yield SqliteTaskStoreBackend()


def test_get_all_tasks_includes_done(backend):
    open_task = backend.create_task(chat_id="chat-1", title="Buy milk", category="errand", created_by="111")
    done_task = backend.create_task(chat_id="chat-1", title="Book dentist", category="appointment", created_by="111")
    backend.mark_done(chat_id="chat-1", task_id=done_task["task_id"])

    all_tasks = backend.get_all_tasks(chat_id="chat-1")
    assert {t["task_id"] for t in all_tasks} == {open_task["task_id"], done_task["task_id"]}
    assert {t["status"] for t in all_tasks} == {"open", "done"}


def test_get_all_tasks_scoped_to_chat(backend):
    backend.create_task(chat_id="chat-1", title="Chat 1 task", category="errand", created_by="111")
    backend.create_task(chat_id="chat-2", title="Chat 2 task", category="errand", created_by="222")

    assert [t["title"] for t in backend.get_all_tasks(chat_id="chat-1")] == ["Chat 1 task"]
    assert [t["title"] for t in backend.get_all_tasks(chat_id="chat-2")] == ["Chat 2 task"]
