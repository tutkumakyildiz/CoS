"""Tests for the web dashboard's task list + auth gate, against a
moto-mocked DynamoDB table — mirrors tests/test_persistence_dynamodb.py's
fixture pattern. No real AWS account, Telegram, or ECS calls.
"""

from __future__ import annotations

import os

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from cos.config import HouseholdConfig
from cos.persistence.dynamodb_backend import DynamoDBTaskStoreBackend, create_table_if_not_exists
from cos.webapp.app import create_app
from cos.webapp.config import WebappSettings

TABLE_NAME = "cos_tasks_webapp_test"
CHAT_ID = "chat-1"


@pytest.fixture()
def settings_and_backend():
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        resource = boto3.resource("dynamodb", region_name="us-east-1")
        create_table_if_not_exists(resource, TABLE_NAME)
        backend = DynamoDBTaskStoreBackend(table_name=TABLE_NAME, region_name="us-east-1", resource=resource)

        household = HouseholdConfig(chat_id=CHAT_ID, partners={"111": "Alex", "222": "Sam"})
        settings = WebappSettings(
            household=household,
            webapp_password="letmein",
            session_secret="test-session-secret",
            dynamodb_table_name=TABLE_NAME,
            aws_region="us-east-1",
        )
        yield settings, backend


@pytest.fixture()
def client(settings_and_backend, monkeypatch):
    settings, backend = settings_and_backend
    # build_backend would construct its own DynamoDBTaskStoreBackend against
    # the real (mocked) table by name — patch it to hand back the exact
    # backend instance the fixture already created and seeded through.
    monkeypatch.setattr("cos.webapp.tasks_view.build_backend", lambda s: backend)
    app = create_app(settings)
    return TestClient(app)


def test_tasks_requires_login(client):
    resp = client.get("/tasks", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_login_wrong_password_rejected(client):
    resp = client.post("/login", data={"password": "wrong"})
    assert resp.status_code == 401


def test_login_then_view_tasks_with_display_names(client, settings_and_backend):
    _, backend = settings_and_backend
    open_task = backend.create_task(chat_id=CHAT_ID, title="Buy milk", category="errand", created_by="111", owner="222")
    done_task = backend.create_task(chat_id=CHAT_ID, title="Book dentist", category="appointment", created_by="222")
    backend.mark_done(chat_id=CHAT_ID, task_id=done_task["task_id"])

    login = client.post("/login", data={"password": "letmein"}, follow_redirects=False)
    assert login.status_code == 303
    assert login.headers["location"] == "/tasks"

    resp = client.get("/tasks")
    assert resp.status_code == 200
    assert "Buy milk" in resp.text
    assert "Book dentist" in resp.text
    # raw Telegram user ids should be resolved to display names, not shown raw
    assert "Sam" in resp.text  # owner of the open task
    assert "Alex" in resp.text  # created_by of the open task
    assert open_task["task_id"] or True  # keep reference, avoid unused-var lint


def test_status_filter(client, settings_and_backend):
    _, backend = settings_and_backend
    backend.create_task(chat_id=CHAT_ID, title="Open one", category="errand", created_by="111")
    done = backend.create_task(chat_id=CHAT_ID, title="Done one", category="errand", created_by="111")
    backend.mark_done(chat_id=CHAT_ID, task_id=done["task_id"])

    client.post("/login", data={"password": "letmein"})
    resp = client.get("/tasks", params={"status": "done"})
    assert "Done one" in resp.text
    assert "Open one" not in resp.text
