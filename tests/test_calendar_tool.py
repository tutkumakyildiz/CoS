"""Tests for calendar_tool — no real Google API calls; _get_calendar_client
is monkeypatched to a mock Resource-like object, same convention as
test_brain.py's monkeypatch.setattr on an extracted function. There's no
moto equivalent for Google APIs (moto is AWS-only), so this is this repo's
first non-AWS external-API test, matching test_search_tool.py's shape.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from cos.config import HouseholdConfig, Settings
from cos.tools.calendar_tool import build_calendar_tools


def _settings(tmp: str, *, configured: bool) -> Settings:
    return Settings(
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
        google_client_id="fake-id" if configured else None,
        google_client_secret="fake-secret" if configured else None,
        google_refresh_token="fake-refresh-token" if configured else None,
    )


def _call(tool, **kwargs):
    return tool(**kwargs)


def test_calendar_not_configured_degrades_to_stub_shape():
    # No monkeypatching here: _get_calendar_client itself is what short-circuits
    # on unconfigured settings, returning None before any Google import/call —
    # this exercises that guard directly, with the real function.
    with tempfile.TemporaryDirectory() as tmp:
        tools = {t.tool_name: t for t in build_calendar_tools(_settings(tmp, configured=False))}
        events = _call(tools["check_upcoming_events"], date_range="2026-09-01..2026-09-30")
        created = _call(tools["create_event"], title="Dentist", date="2026-09-03")

    assert events == {"connected": False, "events": [], "note": "Calendar integration not yet configured."}
    assert created == {"connected": False, "note": "Calendar integration not yet configured; event not created."}


def test_check_upcoming_events_reshapes_real_response(monkeypatch):
    client = MagicMock()
    client.events.return_value.list.return_value.execute.return_value = {
        "items": [
            {"summary": "Soccer practice", "start": {"date": "2026-09-05"}},
            {"summary": "Dentist", "start": {"dateTime": "2026-09-10T14:00:00Z"}},
        ]
    }
    monkeypatch.setattr("cos.tools.calendar_tool._get_calendar_client", lambda settings: client)

    with tempfile.TemporaryDirectory() as tmp:
        tools = {t.tool_name: t for t in build_calendar_tools(_settings(tmp, configured=True))}
        result = _call(tools["check_upcoming_events"], date_range="2026-09-01..2026-09-30")

    assert result["connected"] is True
    assert result["events"] == [
        {"title": "Soccer practice", "start": "2026-09-05"},
        {"title": "Dentist", "start": "2026-09-10T14:00:00Z"},
    ]


def test_create_event_reshapes_real_response(monkeypatch):
    client = MagicMock()
    client.events.return_value.insert.return_value.execute.return_value = {
        "id": "abc123",
        "htmlLink": "https://calendar.google.com/event?eid=abc123",
    }
    monkeypatch.setattr("cos.tools.calendar_tool._get_calendar_client", lambda settings: client)

    with tempfile.TemporaryDirectory() as tmp:
        tools = {t.tool_name: t for t in build_calendar_tools(_settings(tmp, configured=True))}
        result = _call(tools["create_event"], title="Dentist", date="2026-09-03")

    assert result == {"connected": True, "event_id": "abc123", "html_link": "https://calendar.google.com/event?eid=abc123"}


def test_calendar_errors_degrade_gracefully(monkeypatch):
    client = MagicMock()
    client.events.return_value.list.return_value.execute.side_effect = RuntimeError("Google API is down")
    client.events.return_value.insert.return_value.execute.side_effect = RuntimeError("Google API is down")
    monkeypatch.setattr("cos.tools.calendar_tool._get_calendar_client", lambda settings: client)

    with tempfile.TemporaryDirectory() as tmp:
        tools = {t.tool_name: t for t in build_calendar_tools(_settings(tmp, configured=True))}
        events = _call(tools["check_upcoming_events"], date_range="2026-09-01..2026-09-30")
        created = _call(tools["create_event"], title="Dentist", date="2026-09-03")

    assert events == {"connected": True, "events": [], "error": "Google API is down"}
    assert created == {"connected": True, "error": "Google API is down"}
