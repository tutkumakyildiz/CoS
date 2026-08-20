"""Sanity tests for Application wiring — no real Telegram/Anthropic credentials
needed, since Application.builder().build() doesn't make network calls.

Retry-on-silent-drop logic used to live here too; it moved to test_brain.py
along with the code it tests (cos.brain.run_instruction) when that logic
was split out of bot.py into brain.py.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from cos.config import HouseholdConfig, Settings
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
