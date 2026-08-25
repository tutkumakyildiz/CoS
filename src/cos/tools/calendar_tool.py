"""`calendar_tool` — real Google Calendar integration (one partner's primary
calendar), degrading to the same `{"connected": false}` stub shape this
module used to always return when Google credentials aren't configured. See
README "Google Calendar setup" for the one-time OAuth setup, and
scripts/authorize_google_calendar.py for obtaining GOOGLE_REFRESH_TOKEN.

The Google client libraries (the "calendar" extra) are imported lazily,
inside _get_calendar_client, not at module level — so a build without that
extra installed can still import this module and use it in its degraded
"not connected" form, same as every other optional integration in this repo
(webapp, agentcore).

Only google_refresh_token is a stored secret. The access token obtained by
refreshing it is never persisted (not written to .env, household.json, or
any deploy file) and is re-derived on every call — this process's Agent
instance is long-lived per chat_id, so caching a built client risks a stale
access token well before the refresh token itself would need rotating.
"""

from __future__ import annotations

import logging
from typing import Any

from strands import tool

from cos.config import Settings

logger = logging.getLogger(__name__)

_CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _get_calendar_client(settings: Settings) -> Any | None:
    """Build a live Google Calendar API client, or None if not configured."""
    if not (settings.google_client_id and settings.google_client_secret and settings.google_refresh_token):
        return None

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials(
        token=None,
        refresh_token=settings.google_refresh_token,
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=_CALENDAR_SCOPES,
    )
    creds.refresh(Request())
    return build("calendar", "v3", credentials=creds)


def build_calendar_tools(settings: Settings) -> list:
    @tool
    def check_upcoming_events(date_range: str) -> dict[str, Any]:
        """Look up upcoming calendar events in a date range (for cross-referencing
        seasonal/recurring tasks, e.g. "soccer season starts").

        Args:
            date_range: ISO range, e.g. "2026-09-01..2026-09-30".

        Returns:
            A dict with `connected: false` if the calendar isn't configured — don't
            block capturing a task on this; just skip setting `recurrence` from
            calendar data. Otherwise `connected: true` and an `events` list
            (title/start), or an `error` note if the lookup itself failed.
        """
        client = _get_calendar_client(settings)
        if client is None:
            return {"connected": False, "events": [], "note": "Calendar integration not yet configured."}

        try:
            start, end = date_range.split("..")
            response = (
                client.events()
                .list(
                    calendarId="primary",
                    timeMin=f"{start}T00:00:00Z",
                    timeMax=f"{end}T23:59:59Z",
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
            events = [
                {"title": e.get("summary", "(untitled)"), "start": e.get("start", {}).get("date") or e.get("start", {}).get("dateTime")}
                for e in response.get("items", [])
            ]
            return {"connected": True, "events": events}
        except Exception as e:
            logger.warning("check_upcoming_events failed for range %r: %s", date_range, e)
            return {"connected": True, "events": [], "error": str(e)}

    @tool
    def create_event(title: str, date: str) -> dict[str, Any]:
        """Create an all-day event on the calendar. Optional — only if you want a
        task to also land on the calendar.

        Args:
            title: Event title.
            date: ISO date (YYYY-MM-DD).

        Returns:
            A dict with `connected: false` if the calendar isn't configured; the task
            was still captured, this just means it isn't also on the calendar.
            Otherwise `connected: true` and the created event's id/link, or an
            `error` note if creation failed.
        """
        client = _get_calendar_client(settings)
        if client is None:
            return {"connected": False, "note": "Calendar integration not yet configured; event not created."}

        try:
            event = (
                client.events()
                .insert(
                    calendarId="primary",
                    body={"summary": title, "start": {"date": date}, "end": {"date": date}},
                )
                .execute()
            )
            return {"connected": True, "event_id": event.get("id"), "html_link": event.get("htmlLink")}
        except Exception as e:
            logger.warning("create_event failed for %r on %s: %s", title, date, e)
            return {"connected": True, "error": str(e)}

    return [check_upcoming_events, create_event]
