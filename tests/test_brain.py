"""Tests for cos.brain — the agent-invocation logic extracted from bot.py
(the "brain"/gateway split — see README "Architecture"). No real
Telegram/Anthropic/AWS calls; the Strands Agent is faked so these exercise
only the retry-on-silent-drop logic and the AgentCore-shaped payload dispatch.

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


def test_invoke_brain_calls_run_instruction_in_local_mode(settings, monkeypatch):
    # settings fixture defaults to agent_mode="local" — invoke_brain should
    # behave exactly like calling run_instruction directly.
    calls = []
    monkeypatch.setattr(
        brain, "run_instruction", lambda s, bot, instr, *, log_context: calls.append((instr, log_context)) or _noop()
    )

    asyncio.run(brain.invoke_brain(settings, bot=None, instruction="do something", log_context="test"))

    assert calls == [("do something", "test")]


def test_invoke_brain_calls_invoke_remote_in_agentcore_mode(settings, monkeypatch):
    agentcore_settings = _with_agentcore_mode(settings)
    calls = []
    monkeypatch.setattr(
        brain, "invoke_remote", lambda s, instr, *, log_context: calls.append((instr, log_context)) or _noop()
    )

    asyncio.run(brain.invoke_brain(agentcore_settings, bot=None, instruction="do something", log_context="test"))

    assert calls == [("do something", "test")]


def test_invoke_remote_calls_invoke_agent_runtime_with_expected_payload(settings, monkeypatch):
    import json

    agentcore_settings = _with_agentcore_mode(settings)
    captured = {}

    class _FakeStream:
        def read(self):
            return b'{"status": "ok"}'

    class _FakeClient:
        def invoke_agent_runtime(self, **kwargs):
            captured.update(kwargs)
            return {"response": _FakeStream()}

    class _FakeSession:
        def __init__(self, profile_name=None, region_name=None):
            captured["profile_name"] = profile_name
            captured["region_name"] = region_name

        def client(self, name):
            captured["client_name"] = name
            return _FakeClient()

    monkeypatch.setattr(brain.boto3, "Session", _FakeSession)

    asyncio.run(brain.invoke_remote(agentcore_settings, "do something", log_context="test"))

    assert captured["client_name"] == "bedrock-agentcore"
    assert captured["agentRuntimeArn"] == agentcore_settings.agentcore_runtime_arn
    assert captured["runtimeSessionId"].startswith(f"cos-chat-{agentcore_settings.household.chat_id}")
    assert json.loads(captured["payload"]) == {"instruction": "do something", "log_context": "test"}


def _with_agentcore_mode(settings: Settings) -> Settings:
    from dataclasses import replace

    return replace(
        settings,
        agent_mode="agentcore",
        agentcore_runtime_arn="arn:aws:bedrock-agentcore:eu-central-1:123456789012:runtime/cos_brain-fake",
    )


async def _noop() -> None:
    return None
