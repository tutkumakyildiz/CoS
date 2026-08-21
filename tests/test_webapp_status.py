"""Tests for the bot status/restart panel — mocks boto3's ECS client
directly rather than hitting real ECS (moto doesn't model ECS service
describe/update in enough depth for this, and it isn't needed: the routes
only ever call describe_services/update_service).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cos.config import HouseholdConfig
from cos.webapp.app import create_app
from cos.webapp.config import WebappSettings


class FakeEcsClient:
    def __init__(self, service=None, raise_on_describe=None, raise_on_update=None):
        self._service = service
        self._raise_on_describe = raise_on_describe
        self._raise_on_update = raise_on_update
        self.update_calls = []

    def describe_services(self, cluster, services):
        if self._raise_on_describe:
            raise self._raise_on_describe
        return {"services": [self._service] if self._service else []}

    def update_service(self, cluster, service, forceNewDeployment):
        if self._raise_on_update:
            raise self._raise_on_update
        self.update_calls.append((cluster, service, forceNewDeployment))
        return {}


@pytest.fixture()
def settings():
    household = HouseholdConfig(chat_id="chat-1", partners={"111": "Alex"})
    return WebappSettings(
        household=household,
        webapp_password="letmein",
        session_secret="test-session-secret",
        aws_region="us-east-1",  # register_tasks_routes builds a DynamoDB backend at app startup
        ecs_cluster="cos-cluster",
        ecs_service="cos-gateway",
    )


def _login(client):
    # follow_redirects=False: /login's 303 goes to /tasks, which would hit
    # a real (unmocked) DynamoDB backend — these tests only care about the
    # status/restart routes, so avoid following that redirect.
    client.post("/login", data={"password": "letmein"}, follow_redirects=False)


def test_status_requires_login(settings, monkeypatch):
    monkeypatch.setattr("cos.webapp.bot_status._ecs_client", lambda s: FakeEcsClient())
    client = TestClient(create_app(settings))
    resp = client.get("/status", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_status_shows_running_service(settings, monkeypatch):
    fake = FakeEcsClient(service={"status": "ACTIVE", "runningCount": 1, "desiredCount": 1, "pendingCount": 0})
    monkeypatch.setattr("cos.webapp.bot_status._ecs_client", lambda s: fake)
    client = TestClient(create_app(settings))
    _login(client)

    resp = client.get("/status")
    assert resp.status_code == 200
    assert "ACTIVE" in resp.text
    assert "cos-gateway" in resp.text


def test_status_surfaces_missing_service(settings, monkeypatch):
    fake = FakeEcsClient(service=None)
    monkeypatch.setattr("cos.webapp.bot_status._ecs_client", lambda s: fake)
    client = TestClient(create_app(settings))
    _login(client)

    resp = client.get("/status")
    assert "No service named" in resp.text


def test_restart_triggers_force_new_deployment(settings, monkeypatch):
    fake = FakeEcsClient(service={"status": "ACTIVE", "runningCount": 1, "desiredCount": 1, "pendingCount": 0})
    monkeypatch.setattr("cos.webapp.bot_status._ecs_client", lambda s: fake)
    client = TestClient(create_app(settings))
    _login(client)

    resp = client.post("/status/restart", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/status?restarted=1"
    assert fake.update_calls == [("cos-cluster", "cos-gateway", True)]


def test_restart_requires_login(settings, monkeypatch):
    monkeypatch.setattr("cos.webapp.bot_status._ecs_client", lambda s: FakeEcsClient())
    client = TestClient(create_app(settings))
    resp = client.post("/status/restart", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"
