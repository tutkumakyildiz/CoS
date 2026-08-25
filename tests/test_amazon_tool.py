"""Tests for the amazon_tool (search_amazon_products) — no real network calls;
the outbound SerpApi request seam (_run_serpapi_amazon_search) is
monkeypatched, same convention as test_search_tool.py's monkeypatch.setattr
on an extracted function.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from cos.config import HouseholdConfig, Settings
from cos.tools.amazon_tool import build_amazon_tools


def _settings(serpapi_api_key: str | None, tmp: str) -> Settings:
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
        serpapi_api_key=serpapi_api_key,
    )


def _call(tool, **kwargs):
    # DecoratedFunctionTool is directly callable like the plain async function
    # it wraps, so this returns a coroutine — run it with asyncio.run.
    return asyncio.run(tool(**kwargs))


def test_search_amazon_products_not_configured_skips_network_call(monkeypatch):
    called = False

    async def _fail_if_called(query: str, api_key: str):
        nonlocal called
        called = True
        raise AssertionError("should not be called when unconfigured")

    monkeypatch.setattr("cos.tools.amazon_tool._run_serpapi_amazon_search", _fail_if_called)

    with tempfile.TemporaryDirectory() as tmp:
        tools = {t.tool_name: t for t in build_amazon_tools(_settings(None, tmp))}
        result = _call(tools["search_amazon_products"], query="dishwasher detergent")

    assert result == {"connected": False, "results": [], "note": "Amazon search not yet configured."}
    assert called is False


def test_search_amazon_products_configured_reshapes_results(monkeypatch):
    async def _fake_search(query: str, api_key: str):
        return {
            "organic_results": [
                {
                    "title": "Cascade Platinum Dishwasher Pods",
                    "asin": "B073CVZ9GZ",
                    "link": "https://www.amazon.com/dp/B073CVZ9GZ/ref=sxin_1",
                    "link_clean": "https://www.amazon.com/dp/B073CVZ9GZ/",
                    "price": "$19.99",
                    "rating": 4.7,
                    "reviews": 42000,
                    "sponsored": False,
                },
                {
                    "title": "Extra field ignored",
                    "link": "https://www.amazon.com/dp/OTHER/",
                    "price": "$9.99",
                },
            ]
        }

    monkeypatch.setattr("cos.tools.amazon_tool._run_serpapi_amazon_search", _fake_search)

    with tempfile.TemporaryDirectory() as tmp:
        tools = {t.tool_name: t for t in build_amazon_tools(_settings("fake-serpapi-key", tmp))}
        result = _call(tools["search_amazon_products"], query="dishwasher detergent")

    assert result["connected"] is True
    assert result["results"][0] == {
        "title": "Cascade Platinum Dishwasher Pods",
        "url": "https://www.amazon.com/dp/B073CVZ9GZ/",
        "price": "$19.99",
        "rating": 4.7,
        "reviews": 42000,
    }


def test_search_amazon_products_falls_back_to_link_without_link_clean(monkeypatch):
    async def _fake_search(query: str, api_key: str):
        return {"organic_results": [{"title": "No clean link", "link": "https://www.amazon.com/dp/X/ref=tag"}]}

    monkeypatch.setattr("cos.tools.amazon_tool._run_serpapi_amazon_search", _fake_search)

    with tempfile.TemporaryDirectory() as tmp:
        tools = {t.tool_name: t for t in build_amazon_tools(_settings("fake-serpapi-key", tmp))}
        result = _call(tools["search_amazon_products"], query="thing")

    assert result["results"][0]["url"] == "https://www.amazon.com/dp/X/ref=tag"


def test_search_amazon_products_respects_max_results(monkeypatch):
    async def _fake_search(query: str, api_key: str):
        return {"organic_results": [{"title": f"Item {i}", "link": f"https://amazon.com/{i}"} for i in range(10)]}

    monkeypatch.setattr("cos.tools.amazon_tool._run_serpapi_amazon_search", _fake_search)

    with tempfile.TemporaryDirectory() as tmp:
        tools = {t.tool_name: t for t in build_amazon_tools(_settings("fake-serpapi-key", tmp))}
        result = _call(tools["search_amazon_products"], query="thing", max_results=2)

    assert len(result["results"]) == 2


def test_search_amazon_products_error_degrades_gracefully(monkeypatch):
    async def _raise(query: str, api_key: str):
        raise RuntimeError("SerpApi is down")

    monkeypatch.setattr("cos.tools.amazon_tool._run_serpapi_amazon_search", _raise)

    with tempfile.TemporaryDirectory() as tmp:
        tools = {t.tool_name: t for t in build_amazon_tools(_settings("fake-serpapi-key", tmp))}
        result = _call(tools["search_amazon_products"], query="dishwasher detergent")

    assert result == {"connected": True, "results": [], "error": "SerpApi is down"}
