"""Tests for cos.brain — the agent-invocation logic extracted from bot.py
(design spec §8's "brain"/gateway split). No real Telegram/Anthropic/AWS
calls; the Strands Agent is faked so these exercise only the retry-on-
silent-drop logic and the AgentCore-shaped payload dispatch.

These are the same cases that used to live in test_bot.py against
bot_module._invoke_agent, moved here along with the code.
"""

from __future__ import annotations

import asyncio
import re
import tempfile
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from cos import brain
from cos.config import HouseholdConfig, Settings
from cos.response_tracker import ResponseTracker


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


class _FakeAgent:
    """Stands in for a real strands Agent — invoke_async runs the next queued
    behavior (a callable that mutates the shared tracker) instead of making a
    real Anthropic/Bedrock call."""

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
    monkeypatch.setattr(brain, "get_agent", lambda settings, bot: agent)
    monkeypatch.setattr(brain, "get_response_tracker", lambda settings: tracker)
    return agent


def _tool_event(name: str) -> SimpleNamespace:
    return SimpleNamespace(tool_use={"name": name})


def test_run_instruction_retries_when_tool_used_but_no_reply(settings, monkeypatch):
    agent = _patch_agent(
        monkeypatch,
        [
            lambda t: t._on_after_tool_call(_tool_event("get_open_tasks")),
            lambda t: t._on_after_tool_call(_tool_event("send_message")),
        ],
    )

    asyncio.run(brain.run_instruction(settings, bot=None, instruction="do something", log_context="test"))

    assert len(agent.instructions) == 2
    assert agent.instructions[1] == brain.RETRY_NUDGE


def test_run_instruction_no_retry_when_replied_first_try(settings, monkeypatch):
    agent = _patch_agent(monkeypatch, [lambda t: t._on_after_tool_call(_tool_event("send_message"))])

    asyncio.run(brain.run_instruction(settings, bot=None, instruction="do something", log_context="test"))

    assert len(agent.instructions) == 1


def test_run_instruction_no_retry_on_genuine_silence(settings, monkeypatch):
    # No tool called at all (e.g. idle chatter correctly ignored) — must not
    # be treated as "did work without replying".
    agent = _patch_agent(monkeypatch, [lambda t: None])

    asyncio.run(brain.run_instruction(settings, bot=None, instruction="lol nice", log_context="test"))

    assert len(agent.instructions) == 1


def test_handle_payload_dispatches_instruction_and_returns_status(settings, monkeypatch):
    agent = _patch_agent(monkeypatch, [lambda t: t._on_after_tool_call(_tool_event("send_message"))])

    result = asyncio.run(
        brain.handle_payload({"instruction": "do something", "log_context": "test"}, settings, bot=None)
    )

    assert result == {"status": "ok"}
    assert agent.instructions == ["do something"]


def test_handle_payload_defaults_log_context_when_omitted(settings, monkeypatch):
    agent = _patch_agent(monkeypatch, [lambda t: t._on_after_tool_call(_tool_event("send_message"))])

    asyncio.run(brain.handle_payload({"instruction": "do something"}, settings, bot=None))

    assert agent.instructions == ["do something"]


def test_today_prefix_contains_iso_date():
    assert re.search(r"\d{4}-\d{2}-\d{2}", brain.today_prefix())
