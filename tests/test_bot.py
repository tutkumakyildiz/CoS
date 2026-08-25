"""Sanity tests for Application wiring — no real Telegram/Anthropic credentials
needed, since Application.builder().build() doesn't make network calls.

Retry-on-silent-drop logic used to live here too; it moved to test_brain.py
along with the code it tests (cos.brain.run_instruction) when that logic
was split out of bot.py into brain.py.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest

from cos.config import HouseholdConfig, Settings
from cos.telegram_bot.bot import _handle_callback, _handle_message, _is_direct_mention, build_application


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


def test_handle_callback_edits_message_to_show_tap_registered(settings, monkeypatch):
    # A tapped button should get instant visual feedback — the original
    # message rewritten with the choice made and its keyboard removed —
    # rather than sitting unchanged until the agent's own confirmation
    # (which can take a few seconds) arrives as a separate message.
    monkeypatch.setattr("cos.telegram_bot.bot.invoke_brain", AsyncMock())

    query = MagicMock()
    query.data = "task-1::Assign to Alex"
    query.from_user = MagicMock(id=111)
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.message = MagicMock(text="Who's taking out the trash?")

    update = MagicMock(callback_query=query)
    context = MagicMock()

    asyncio.run(_handle_callback(update, context, settings))

    query.answer.assert_awaited_once()
    query.edit_message_text.assert_awaited_once_with(
        text="Who's taking out the trash?\n\n☑️ Alex: Assign to Alex",
        reply_markup=None,
    )


def test_handle_callback_still_invokes_brain_if_edit_fails(settings, monkeypatch):
    # The edit is best-effort UI polish — a failure there (e.g. a stale
    # message) must not stop the actual assignment logic from running.
    brain_mock = AsyncMock()
    monkeypatch.setattr("cos.telegram_bot.bot.invoke_brain", brain_mock)

    query = MagicMock()
    query.data = "task-1::Assign to Alex"
    query.from_user = MagicMock(id=111)
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock(side_effect=RuntimeError("message too old"))
    query.message = MagicMock(text="Who's taking out the trash?")

    update = MagicMock(callback_query=query)
    context = MagicMock()

    asyncio.run(_handle_callback(update, context, settings))

    brain_mock.assert_awaited_once()


def test_is_direct_mention_true_for_real_mention_entity():
    message = MagicMock()
    message.parse_entities.return_value = {"entity": "@cos_household_bot"}
    assert _is_direct_mention(message, "cos_household_bot") is True


def test_is_direct_mention_false_without_matching_entity():
    message = MagicMock()
    message.parse_entities.return_value = {}
    assert _is_direct_mention(message, "cos_household_bot") is False


def test_is_direct_mention_false_when_bot_username_unknown():
    message = MagicMock()
    message.parse_entities.return_value = {"entity": "@cos_household_bot"}
    assert _is_direct_mention(message, None) is False


def test_handle_message_flags_direct_mention_in_instruction(settings, monkeypatch):
    brain_mock = AsyncMock()
    monkeypatch.setattr("cos.telegram_bot.bot.invoke_brain", brain_mock)

    message = MagicMock(text="@cos_household_bot book the dentist for Sep 3")
    message.parse_entities.return_value = {"entity": "@cos_household_bot"}
    update = MagicMock()
    update.effective_message = message
    update.effective_user = MagicMock(id=111)

    context = MagicMock()
    context.bot.username = "cos_household_bot"

    asyncio.run(_handle_message(update, context, settings))

    instruction = brain_mock.call_args.args[2]
    assert "directly @-mentioned you" in instruction


def test_handle_message_no_mention_note_for_passive_mention(settings, monkeypatch):
    brain_mock = AsyncMock()
    monkeypatch.setattr("cos.telegram_bot.bot.invoke_brain", brain_mock)

    message = MagicMock(text="we need to book the dentist")
    message.parse_entities.return_value = {}
    update = MagicMock()
    update.effective_message = message
    update.effective_user = MagicMock(id=111)

    context = MagicMock()
    context.bot.username = "cos_household_bot"

    asyncio.run(_handle_message(update, context, settings))

    instruction = brain_mock.call_args.args[2]
    assert "directly @-mentioned you" not in instruction
