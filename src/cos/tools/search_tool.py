"""`search_tool` — general web search via Tavily, for things not answerable
from the task list (store hours, a phone number, "find a plumber near us",
a general fact). Not a Places/Maps API: results are whatever Tavily's web
search returns for the query text, with no guaranteed structured
address/phone/hours.

Reuses `strands_tools.tavily.tavily_search` (strands-agents-tools is already
a runtime dependency) rather than re-implementing the Tavily HTTP call, but
wraps it in a small, household-appropriate `web_search(query)` tool that
degrades gracefully when TAVILY_API_KEY isn't set — matching calendar_tool's
stub contract — instead of tavily_search's own behavior of raising ValueError
on a missing key and exposing 15 Tavily-specific params the agent doesn't
need.
"""

from __future__ import annotations

import ast
import logging
from typing import Any

from strands import tool
from strands_tools import tavily

from cos.config import Settings

logger = logging.getLogger(__name__)


async def _run_tavily_search(query: str) -> dict[str, Any]:
    """The one seam tests patch — the actual outbound call to Tavily.

    tavily_search returns {"status": ..., "content": [{"text": str(data)}]},
    where `text` is a Python dict stringified with str() (repr syntax, e.g.
    single-quoted strings) rather than JSON — so it's parsed back with
    ast.literal_eval, not json.loads.
    """
    result = await tavily.tavily_search(query=query, max_results=5)
    if result.get("status") != "success":
        message = result.get("content", [{}])[0].get("text", "Search failed.")
        raise RuntimeError(message)
    raw_text = result["content"][0]["text"]
    return ast.literal_eval(raw_text)


def build_search_tools(settings: Settings) -> list:
    @tool
    async def web_search(query: str) -> dict[str, Any]:
        """General web search — for things not in the task list: store hours,
        a phone number, "find a plumber near us", a general fact. Not a
        maps/business-directory lookup: results are whatever the web search
        returns for the query text, with no guaranteed structured
        address/phone/hours — don't state one unless it's actually in a result.

        Args:
            query: The search query, as plain text.

        Returns:
            A dict with `connected: false` if web search isn't configured yet
            (don't block on this — just say you can't look that up). Otherwise
            `connected: true` and a short `results` list (title/url/content
            snippet, up to 5), or an `error` note if the search itself failed.
        """
        if not settings.tavily_api_key:
            return {"connected": False, "results": [], "note": "Web search not yet configured."}

        try:
            data = await _run_tavily_search(query)
        except Exception as e:
            logger.warning("web_search failed for query %r: %s", query, e)
            return {"connected": True, "results": [], "error": str(e)}

        results = [
            {"title": r.get("title"), "url": r.get("url"), "content": r.get("content")}
            for r in data.get("results", [])[:5]
        ]
        return {"connected": True, "results": results}

    return [web_search]
