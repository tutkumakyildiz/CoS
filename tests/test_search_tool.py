"""Tests for the search_tool (web_search) — no real network calls; the
outbound Tavily request seam (_run_tavily_search) is monkeypatched, same
convention as test_brain.py's monkeypatch.setattr on an extracted function.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from cos.config import HouseholdConfig, Settings
from cos.tools.search_tool import build_search_tools


def _settings(tavily_api_key: str | None, tmp: str) -> Settings:
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
        tavily_api_key=tavily_api_key,
    )


def _call(tool, **kwargs):
    # DecoratedFunctionTool is directly callable like the plain async function
    # it wraps, so this returns a coroutine — run it with asyncio.run.
    return asyncio.run(tool(**kwargs))


def test_web_search_not_configured_skips_network_call(monkeypatch):
    called = False

    async def _fail_if_called(query: str):
        nonlocal called
        called = True
        raise AssertionError("should not be called when unconfigured")

    monkeypatch.setattr("cos.tools.search_tool._run_tavily_search", _fail_if_called)

    with tempfile.TemporaryDirectory() as tmp:
        tools = {t.tool_name: t for t in build_search_tools(_settings(None, tmp))}
        result = _call(tools["web_search"], query="plumber near us")

    assert result == {"connected": False, "results": [], "note": "Web search not yet configured."}
    assert called is False


def test_web_search_configured_reshapes_results(monkeypatch):
    async def _fake_search(query: str):
        return {
            "results": [
                {"title": "Ace Plumbing", "url": "https://ace.example", "content": "24/7 plumber", "score": 0.9},
                {"title": "Extra field ignored", "url": "https://x.example", "content": "..."},
            ]
        }

    monkeypatch.setattr("cos.tools.search_tool._run_tavily_search", _fake_search)

    with tempfile.TemporaryDirectory() as tmp:
        tools = {t.tool_name: t for t in build_search_tools(_settings("fake-tavily-key", tmp))}
        result = _call(tools["web_search"], query="plumber near us")

    assert result["connected"] is True
    assert result["results"][0] == {
        "title": "Ace Plumbing",
        "url": "https://ace.example",
        "content": "24/7 plumber",
    }


def test_web_search_error_degrades_gracefully(monkeypatch):
    async def _raise(query: str):
        raise RuntimeError("Tavily is down")

    monkeypatch.setattr("cos.tools.search_tool._run_tavily_search", _raise)

    with tempfile.TemporaryDirectory() as tmp:
        tools = {t.tool_name: t for t in build_search_tools(_settings("fake-tavily-key", tmp))}
        result = _call(tools["web_search"], query="plumber near us")

    assert result == {"connected": True, "results": [], "error": "Tavily is down"}
