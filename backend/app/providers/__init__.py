"""Provider registry.

One place decides which implementation backs each contract. Services ask for a
capability; they never construct a vendor client themselves.

When a key is absent the registry falls back to the mock and says so in the
logs, so a missing credential degrades a feature instead of crashing startup —
and `GET /health` reports which providers are real.
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import settings
from app.core.logging import get_logger
from app.providers.base import (
    EmailProvider,
    FetchedPage,
    FetchProvider,
    LLMProvider,
    LLMResponse,
    Message,
    SearchProvider,
    SearchResult,
    SentMessage,
    ToolCall,
    ToolResult,
    ToolSpec,
)
from app.providers.gemini import GeminiProvider
from app.providers.mocks import MockEmailProvider, MockLLMProvider, MockSearchProvider
from app.providers.resend import ResendProvider
from app.providers.tavily import TavilyProvider

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def get_search_provider() -> SearchProvider:
    if settings.search_enabled:
        return TavilyProvider()
    logger.warning("TAVILY_API_KEY unset — using the mock search provider")
    return MockSearchProvider()


@lru_cache(maxsize=1)
def get_fetch_provider() -> FetchProvider:
    # Tavily covers both tools, so the same instance backs search and fetch.
    return get_search_provider()  # type: ignore[return-value]


@lru_cache(maxsize=1)
def get_llm_provider() -> LLMProvider:
    if settings.llm_enabled:
        return GeminiProvider()
    logger.warning("GEMINI_API_KEY unset — using the mock LLM provider")
    return MockLLMProvider()


@lru_cache(maxsize=1)
def get_email_provider() -> EmailProvider:
    if settings.email_enabled:
        return ResendProvider()
    logger.warning("RESEND_API_KEY unset — using the mock email provider")
    return MockEmailProvider()


def reset_providers() -> None:
    """Drop cached providers. Used by tests that swap in a mock."""
    get_search_provider.cache_clear()
    get_fetch_provider.cache_clear()
    get_llm_provider.cache_clear()
    get_email_provider.cache_clear()


__all__ = [
    "EmailProvider",
    "FetchProvider",
    "FetchedPage",
    "LLMProvider",
    "LLMResponse",
    "Message",
    "SearchProvider",
    "SearchResult",
    "SentMessage",
    "ToolCall",
    "ToolResult",
    "ToolSpec",
    "get_email_provider",
    "get_fetch_provider",
    "get_llm_provider",
    "get_search_provider",
    "reset_providers",
]
