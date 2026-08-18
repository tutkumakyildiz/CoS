"""`calendar_tool` — spec §4.2. Week 2 item; stubbed for Week 1.

The system prompt (spec §5) tells the agent to consult this for seasonal/
recurring tasks, so it needs to exist and answer *something* sane rather than
fail as an unknown tool — it just always reports "not connected yet" for now.
Swap the bodies below for a real Google Calendar API wrapper (or a community
Strands tool, if one proves solid) without changing the tool names/signatures.
"""

from __future__ import annotations

from typing import Any

from strands import tool


def build_calendar_tools() -> list:
    @tool
    def check_upcoming_events(date_range: str) -> dict[str, Any]:
        """Look up upcoming calendar events in a date range (for cross-referencing
        seasonal/recurring tasks, e.g. "soccer season starts").

        Args:
            date_range: Human-readable or ISO range, e.g. "2026-09-01..2026-09-30".

        Returns:
            A dict with `connected: false` for now — calendar integration isn't wired
            up yet (Week 2). Don't block capturing a task on this; just skip setting
            `recurrence` from calendar data until it's connected.
        """
        return {"connected": False, "events": [], "note": "Calendar integration not yet configured."}

    @tool
    def create_event(title: str, date: str) -> dict[str, Any]:
        """Create an event on the shared calendar. Optional — only if you want a
        task to also land on the calendar.

        Args:
            title: Event title.
            date: ISO date (YYYY-MM-DD).

        Returns:
            A dict with `connected: false` for now — calendar integration isn't wired
            up yet (Week 2).
        """
        return {"connected": False, "note": "Calendar integration not yet configured; event not created."}

    return [check_upcoming_events, create_event]
