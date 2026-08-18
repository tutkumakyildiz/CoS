"""Sanity tests for Application wiring — no real Telegram/Anthropic credentials
needed, since Application.builder().build() doesn't make network calls.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from cos.config import HouseholdConfig, Settings
from cos.response_tracker import ResponseTracker
from cos.telegram_bot import bot as bot_module
from cos.telegram_bot.bot import build_application


@pytest.fixture()
def settings():
    with tempfile.TemporaryDirectory() as tmp:
        yield Settings(
            telegram_bot_token="123456:AAfake-token-for-construction-test",
            anthropic_api_key="fake-key",
            model_id="claude-sonnet-4-5-20250929",
            db_path=Path(tmp) / "test.db",
            household=HouseholdConfig(chat_id="-100123", partners={"111": "Alex", "222": "Sam"}),
            nudge_hour=9,
            nudge_timezone=ZoneInfo("UTC"),
            metrics_hour=10,
            metrics_minute=0,
            metrics_weekday=0,
        )


def test_build_application_registers_daily_nudge_job(settings):
    app = build_application(settings)
    jobs = app.job_queue.get_jobs_by_name("daily_nudge_check")
    assert len(jobs) == 1


def test_build_application_registers_weekly_metrics_job(settings):
    app = build_application(settings)
    jobs = app.job_queue.get_jobs_by_name("weekly_metrics_check")
    assert len(jobs) == 1


def test_build_application_raises_without_job_queue_extra(settings, monkeypatch):
    # If someone installs plain python-telegram-bot (no [job-queue] extra),
    # Application.job_queue is None — make sure we fail loudly, not silently
    # skip the scheduler.
    from telegram.ext import ApplicationBuilder

    monkeypatch.setattr(ApplicationBuilder, "build", lambda self: _AppWithoutJobQueue(self))

    class _AppWithoutJobQueue:
        def __init__(self, builder):
            self.job_queue = None

        def add_handler(self, *_args, **_kwargs):
            pass

    with pytest.raises(RuntimeError, match="JobQueue not available"):
        build_application(settings)


class _FakeAgent:
    """Stands in for a real strands Agent — invoke_async runs the next queued
    behavior (a callable that mutates the shared tracker) instead of making a
    real Anthropic call."""

    def __init__(self, tracker: ResponseTracker, behaviors: list):
        self.tracker = tracker
        self.behaviors = list(behaviors)
        self.instructions: list[str] = []

    async def invoke_async(self, instruction: str) -> None:
        self.instructions.append(instruction)
        self.behaviors.pop(0)(self.tracker)


def _patch_agent(monkeypatch, behaviors: list):
    tracker = ResponseTracker()
    agent = _FakeAgent(tracker, behaviors)
    monkeypatch.setattr(bot_module, "get_agent", lambda settings, bot: agent)
    monkeypatch.setattr(bot_module, "get_response_tracker", lambda settings: tracker)
    return agent


def _tool_event(name: str) -> SimpleNamespace:
    return SimpleNamespace(tool_use={"name": name})


def test_invoke_agent_retries_when_tool_used_but_no_reply(settings, monkeypatch):
    agent = _patch_agent(
        monkeypatch,
        [
            lambda t: t._on_after_tool_call(_tool_event("get_open_tasks")),
            lambda t: t._on_after_tool_call(_tool_event("send_message")),
        ],
    )

    asyncio.run(bot_module._invoke_agent(settings, bot=None, instruction="do something", log_context="test"))

    assert len(agent.instructions) == 2
    assert agent.instructions[1] == bot_module._RETRY_NUDGE


def test_invoke_agent_no_retry_when_replied_first_try(settings, monkeypatch):
    agent = _patch_agent(monkeypatch, [lambda t: t._on_after_tool_call(_tool_event("send_message"))])

    asyncio.run(bot_module._invoke_agent(settings, bot=None, instruction="do something", log_context="test"))

    assert len(agent.instructions) == 1


def test_invoke_agent_no_retry_on_genuine_silence(settings, monkeypatch):
    # No tool called at all (e.g. idle chatter correctly ignored) — must not
    # be treated as "did work without replying".
    agent = _patch_agent(monkeypatch, [lambda t: None])

    asyncio.run(bot_module._invoke_agent(settings, bot=None, instruction="lol nice", log_context="test"))

    assert len(agent.instructions) == 1
