"""`amazon_tool` — Amazon product search via SerpApi's Amazon Search engine,
for requests like "find a dishwasher detergent on Amazon" or "compare
laundry pods and send me a link".

Scope is deliberately narrow: this tool finds and compares products and
returns links. It never purchases anything, never touches a cart or
checkout, and never handles payment details — completing an order stays a
manual step for whoever wants the item. See BASE_SYSTEM_PROMPT's
ON-DEMAND QUERIES section for how the agent is told to use it.

Degrades to the same `{"connected": false}` stub shape as search_tool and
calendar_tool when SERPAPI_API_KEY isn't set, rather than raising.

SerpApi is called directly over HTTP (no `strands_tools` wrapper exists for
it, unlike Tavily) using aiohttp — already a transitive dependency via
strands-agents-tools, but listed explicitly in pyproject.toml since this
module calls it directly.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
from strands import tool

from cos.config import Settings

logger = logging.getLogger(__name__)

_SERPAPI_ENDPOINT = "https://serpapi.com/search.json"


async def _run_serpapi_amazon_search(query: str, api_key: str) -> dict[str, Any]:
    """The one seam tests patch — the actual outbound call to SerpApi."""
    params = {
        "engine": "amazon",
        "k": query,
        "amazon_domain": "amazon.com",
        "api_key": api_key,
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(_SERPAPI_ENDPOINT, params=params) as response:
            data = await response.json()
            if response.status != 200:
                message = data.get("error", f"SerpApi request failed with status {response.status}")
                raise RuntimeError(message)
            return data


def build_amazon_tools(settings: Settings) -> list:
    @tool
    async def search_amazon_products(query: str, max_results: int = 5) -> dict[str, Any]:
        """Search Amazon for products — for requests like "find a dishwasher
        detergent on Amazon" or "compare laundry pods and send me a link".

        Finds and compares products only — never adds to a cart, checks out, or
        handles payment. Present the option(s) and their link(s) and let whoever
        asked complete the purchase themselves.

        Args:
            query: The product search query, as plain text (e.g. "dishwasher
                detergent pods").
            max_results: How many results to return (default 5).

        Returns:
            A dict with `connected: false` if Amazon search isn't configured yet
            (don't block on this — just say you can't look that up). Otherwise
            `connected: true` and a `results` list (title/url/price/rating/
            reviews, up to max_results), or an `error` note if the search itself
            failed. Only state a price or rating that's actually in a result.
        """
        if not settings.serpapi_api_key:
            return {"connected": False, "results": [], "note": "Amazon search not yet configured."}

        try:
            data = await _run_serpapi_amazon_search(query, settings.serpapi_api_key)
        except Exception as e:
            logger.warning("search_amazon_products failed for query %r: %s", query, e)
            return {"connected": True, "results": [], "error": str(e)}

        results = [
            {
                "title": r.get("title"),
                "url": r.get("link_clean") or r.get("link"),
                "price": r.get("price"),
                "rating": r.get("rating"),
                "reviews": r.get("reviews"),
            }
            for r in data.get("organic_results", [])[:max_results]
        ]
        return {"connected": True, "results": results}

    return [search_amazon_products]
