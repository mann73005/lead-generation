"""In-process stand-ins for every external provider.

The brief allows mocking a provider that is unavailable, on the condition that
"the mock still has to fail realistically". These therefore reproduce the
failure modes the real services actually exhibit, not just their happy paths:

  * search returns an empty list for queries nothing matches, which is a normal
    answer and must not be confused with an error;
  * fetch silently drops URLs it cannot render, so callers never get to assume
    len(pages) == len(urls);
  * the LLM raises `ProviderUnavailableError` on a deterministic subset of
    calls, mirroring the 503s the real flash models return under load;
  * email rejects addresses that look undeliverable and refuses oversized
    payloads, the two rejections a gateway issues most often.

Failures are seeded rather than random so a test that trips one trips it every
time.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.core.exceptions import ProviderError, ProviderUnavailableError
from app.core.logging import get_logger
from app.providers.base import (
    FetchedPage,
    LLMResponse,
    Message,
    SearchResult,
    SentMessage,
    ToolCall,
    ToolSpec,
)

logger = get_logger(__name__)


def _stable_fraction(value: str) -> float:
    """Deterministic 0..1 derived from a string, for reproducible failures."""
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") / 0xFFFFFFFF


#: Deliberately fictional companies and people. Naming real businesses in a
#: fixture invites them into test assertions and, worse, into generated sample
#: emails that then make claims about an actual company.
_FIXTURE_PAGES: dict[str, tuple[str, str]] = {
    "https://example-apparel.invalid/leadership": (
        "Leadership — Example Apparel",
        "Example Apparel is a fictional apparel retailer used for testing. "
        "Asha Example serves as Head of Merchandising, overseeing assortment "
        "planning across its stores. The company employs approximately 400 "
        "people and announced a direct-to-consumer expansion this year.",
    ),
    "https://sample-fashion.invalid/team": (
        "Our Team — Sample Fashion",
        "Sample Fashion is a fictional fashion brand used for testing. "
        "Dev Sample leads Demand Planning. The company has around 250 "
        "employees and recently reported markdown pressure on winter stock.",
    ),
}


class MockSearchProvider:
    name = "mock-search"

    def __init__(self, *, fail_queries: set[str] | None = None) -> None:
        self._fail_queries = fail_queries or set()

    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        if query in self._fail_queries:
            raise ProviderUnavailableError(
                "Mock search provider is rate limited", details={"provider": self.name}
            )

        lowered = query.lower()
        # No match is an empty list, never an exception — callers must handle
        # "found nothing" as an ordinary outcome.
        if not any(term in lowered for term in ("fashion", "apparel", "merchandising", "retail")):
            logger.info("mock search %r -> 0 results", query[:50])
            return []

        return [
            SearchResult(title=title, url=url, snippet=body[:180], score=0.9 - index * 0.1)
            for index, (url, (title, body)) in enumerate(_FIXTURE_PAGES.items())
        ][:max_results]

    def fetch(self, urls: list[str], *, max_chars: int = 20_000) -> list[FetchedPage]:
        pages: list[FetchedPage] = []
        for url in urls:
            fixture = _FIXTURE_PAGES.get(url)
            if fixture is None:
                # Dropped, not raised — exactly what the real extractor does
                # with a page it cannot render.
                logger.info("mock fetch could not render %s", url)
                continue
            title, body = fixture
            pages.append(FetchedPage(url=url, title=title, content=body[:max_chars]))
        return pages


class MockLLMProvider:
    """Replays scripted responses, failing on a deterministic subset of calls."""

    name = "mock-llm"

    def __init__(
        self,
        *,
        responses: list[LLMResponse] | None = None,
        unavailable_rate: float = 0.0,
    ) -> None:
        self._responses = list(responses or [])
        self._unavailable_rate = unavailable_rate
        self.calls: list[dict[str, Any]] = []

    def generate(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        tools: list[ToolSpec] | None = None,
        json_schema: dict[str, Any] | None = None,
        temperature: float = 0.2,
    ) -> LLMResponse:
        fingerprint = json.dumps(
            [m.text for m in messages] + [system or ""], sort_keys=True, default=str
        )
        self.calls.append({"messages": len(messages), "tools": [t.name for t in tools or []]})

        if self._unavailable_rate and _stable_fraction(fingerprint) < self._unavailable_rate:
            raise ProviderUnavailableError(
                "Mock LLM is overloaded", details={"provider": self.name}
            )

        if self._responses:
            return self._responses.pop(0)

        if tools:
            return LLMResponse(
                text="",
                tool_calls=[ToolCall(id="mock-1", name=tools[0].name, arguments={"query": "fashion India"})],
                model=self.name,
            )
        return LLMResponse(text="{}" if json_schema else "mock response", tool_calls=[], model=self.name)


class MockEmailProvider:
    """Captures sends in memory and applies a gateway's usual rejections."""

    name = "mock-email"

    MAX_BYTES = 10 * 1024 * 1024

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def send(
        self,
        *,
        to: str,
        subject: str,
        html: str,
        text: str,
        from_name: str,
        from_address: str,
        headers: dict[str, str] | None = None,
    ) -> SentMessage:
        if "@" not in to or to.endswith("@") or " " in to:
            raise ProviderError(
                "Mock gateway rejected an invalid recipient address",
                details={"provider": self.name, "to": to},
            )
        if len(html.encode("utf-8")) > self.MAX_BYTES:
            raise ProviderError(
                "Mock gateway rejected an oversized message",
                details={"provider": self.name},
            )
        if to.lower().startswith("bounce@"):
            raise ProviderError(
                "Mock gateway reported a hard bounce",
                details={"provider": self.name, "to": to},
            )

        index = len(self.sent) + 1
        self.sent.append(
            {"to": to, "subject": subject, "html": html, "text": text, "headers": headers or {}}
        )
        return SentMessage(provider_message_id=f"mock-{index}", to=to, provider=self.name)
