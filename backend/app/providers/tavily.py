"""Tavily — provides both the search and the fetch tool.

One vendor covers both tools the brief asks for, which keeps the agent loop to
a single credential and a single failure mode to reason about.
"""

from __future__ import annotations

from app.core.config import settings
from app.core.exceptions import ProviderNotConfiguredError
from app.core.logging import get_logger
from app.providers.base import FetchedPage, SearchResult
from app.providers.http import post_json

logger = get_logger(__name__)

SEARCH_URL = "https://api.tavily.com/search"
EXTRACT_URL = "https://api.tavily.com/extract"


class TavilyProvider:
    """Implements both `SearchProvider` and `FetchProvider`."""

    name = "tavily"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or settings.tavily_api_key
        if not self._api_key:
            raise ProviderNotConfiguredError(
                "TAVILY_API_KEY is not set, so lead discovery cannot run",
                details={"provider": self.name},
            )

    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        body = post_json(
            SEARCH_URL,
            {
                "api_key": self._api_key,
                "query": query,
                "max_results": max(1, min(max_results, 20)),
                "search_depth": "basic",
            },
            provider=self.name,
            timeout=45.0,
        )

        results = [
            SearchResult(
                title=item.get("title") or item.get("url", ""),
                url=item["url"],
                snippet=item.get("content", "") or "",
                score=item.get("score"),
            )
            for item in body.get("results", [])
            if item.get("url")
        ]
        logger.info("tavily search %r -> %d results", query[:60], len(results))
        return results

    def fetch(self, urls: list[str], *, max_chars: int = 20_000) -> list[FetchedPage]:
        if not urls:
            return []

        body = post_json(
            EXTRACT_URL,
            {"api_key": self._api_key, "urls": urls[:10]},
            provider=self.name,
            timeout=90.0,
        )

        pages: list[FetchedPage] = []
        for item in body.get("results", []):
            raw = item.get("raw_content") or ""
            pages.append(
                FetchedPage(
                    url=item.get("url", ""),
                    content=raw[:max_chars],
                    truncated=len(raw) > max_chars,
                )
            )

        failed = body.get("failed_results") or []
        if failed:
            # Logged, not raised: a page that will not render is normal on the
            # open web, and the rest of the batch is still usable.
            logger.info("tavily extract skipped %d unreachable url(s)", len(failed))

        return pages
