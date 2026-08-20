"""Tests for DynamoDBTaskStoreBackend against a mocked DynamoDB (moto) — no
real AWS account or credentials needed. Mirrors test_task_store.py's SQLite
coverage so both backends are held to the same behavioral contract.
"""

from __future__ import annotations

import os
from datetime import date, timedelta

import boto3
import pytest
from moto import mock_aws

from cos.persistence.dynamodb_backend import DynamoDBTaskStoreBackend, create_table_if_not_exists

TABLE_NAME = "cos_tasks_test"


@pytest.fixture()
def backend():
    # moto needs *some* credentials present even though nothing real is ever
    # called — these never touch a real account.
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        resource = boto3.resource("dynamodb", region_name="us-east-1")
        create_table_if_not_exists(resource, TABLE_NAME)
        yield DynamoDBTaskStoreBackend(table_name=TABLE_NAME, region_name="us-east-1", resource=resource)


def test_create_and_get_open_tasks(backend):
    task = backend.create_task(chat_id="chat-1", title="Buy soccer shoes", category="errand", created_by="111")
    assert task["status"] == "open"
    assert task["chat_id"] == "chat-1"

    open_tasks = backend.get_open_tasks(chat_id="chat-1")
    assert [t["task_id"] for t in open_tasks] == [task["task_id"]]


def test_update_task_owner(backend):
    task = backend.create_task(chat_id="chat-1", title="Renew passport", category="admin", created_by="111")
    updated = backend.update_task(chat_id="chat-1", task_id=task["task_id"], fields={"owner": "222"})
    assert updated["owner"] == "222"


def test_update_task_missing_raises(backend):
    with pytest.raises(ValueError, match="No task"):
        backend.update_task(chat_id="chat-1", task_id="does-not-exist", fields={"owner": "222"})


def test_mark_done_removes_from_open(backend):
    task = backend.create_task(chat_id="chat-1", title="Book dentist", category="appointment", created_by="111")
    backend.mark_done(chat_id="chat-1", task_id=task["task_id"])
    assert backend.get_open_tasks(chat_id="chat-1") == []


def test_mark_done_missing_raises(backend):
    with pytest.raises(ValueError, match="No task"):
        backend.mark_done(chat_id="chat-1", task_id="does-not-exist")


def test_overdue_tasks(backend):
    backend.create_task(
        chat_id="chat-1", title="Pay HOA fee", category="admin", created_by="111", due_date="2000-01-01"
    )
    overdue = backend.get_overdue_tasks(chat_id="chat-1")
    assert [t["title"] for t in overdue] == ["Pay HOA fee"]


def test_due_soon_tasks_excludes_overdue_and_far_future(backend):
    soon = (date.today() + timedelta(days=1)).isoformat()
    far = (date.today() + timedelta(days=30)).isoformat()
    overdue = (date.today() - timedelta(days=1)).isoformat()
    backend.create_task(chat_id="chat-1", title="Soon", category="errand", created_by="111", due_date=soon)
    backend.create_task(chat_id="chat-1", title="Far", category="errand", created_by="111", due_date=far)
    backend.create_task(chat_id="chat-1", title="Overdue", category="errand", created_by="111", due_date=overdue)

    due_soon = backend.get_due_soon_tasks(chat_id="chat-1", days=2)
    assert [t["title"] for t in due_soon] == ["Soon"]


def test_chat_isolation(backend):
    backend.create_task(chat_id="chat-1", title="A", category="errand", created_by="111")
    backend.create_task(chat_id="chat-2", title="B", category="errand", created_by="222")

    assert len(backend.get_open_tasks(chat_id="chat-1")) == 1
    assert len(backend.get_open_tasks(chat_id="chat-2")) == 1


def test_weekly_metrics_counts_and_percentages(backend):
    t1 = backend.create_task(chat_id="chat-1", title="A", category="errand", created_by="111")
    backend.create_task(chat_id="chat-1", title="B", category="errand", created_by="222")
    backend.mark_done(chat_id="chat-1", task_id=t1["task_id"])

    metrics = backend.get_weekly_metrics(chat_id="chat-1", days=7)

    assert metrics["captured_total"] == 2
    assert metrics["captured_pct_by_owner"]["111"] == 50.0
    assert metrics["captured_pct_by_owner"]["222"] == 50.0
    assert metrics["completed_total"] == 1
    assert metrics["resolved_without_nudge_pct"] == 100.0


def test_weekly_metrics_empty_window(backend):
    metrics = backend.get_weekly_metrics(chat_id="chat-1", days=7)

    assert metrics["captured_total"] == 0
    assert metrics["completed_total"] == 0
    assert metrics["resolved_without_nudge_pct"] == 0.0
