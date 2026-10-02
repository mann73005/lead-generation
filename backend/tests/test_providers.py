"""Provider contract tests.

These run entirely against the mocks — no network, no keys. Their job is to
pin down the failure behaviour callers are allowed to rely on.
"""

import pytest

from app.core.exceptions import ProviderError, ProviderUnavailableError
from app.providers.base import (
    EmailProvider,
    FetchProvider,
    LLMProvider,
    Message,
    SearchProvider,
    ToolSpec,
)
from app.providers.mocks import MockEmailProvider, MockLLMProvider, MockSearchProvider


def test_mocks_satisfy_the_protocols() -> None:
    """A mock that drifts from the contract is worse than no mock."""
    search = MockSearchProvider()
    assert isinstance(search, SearchProvider)
    assert isinstance(search, FetchProvider)
    assert isinstance(MockLLMProvider(), LLMProvider)
    assert isinstance(MockEmailProvider(), EmailProvider)


# --------------------------------------------------------------------------
# Search / fetch
# --------------------------------------------------------------------------


def test_no_matches_is_an_empty_list_not_an_exception() -> None:
    assert MockSearchProvider().search("underwater basket weaving") == []


def test_search_returns_results_for_a_relevant_query() -> None:
    results = MockSearchProvider().search("fashion merchandising India")
    assert results
    assert all(r.url.startswith("http") for r in results)


def test_search_respects_max_results() -> None:
    assert len(MockSearchProvider().search("apparel", max_results=1)) == 1


def test_rate_limiting_raises_a_retryable_error() -> None:
    provider = MockSearchProvider(fail_queries={"boom"})
    with pytest.raises(ProviderUnavailableError):
        provider.search("boom")


def test_fetch_drops_unreachable_urls_instead_of_failing_the_batch() -> None:
    """Callers must never assume len(pages) == len(urls)."""
    provider = MockSearchProvider()
    good = next(iter(provider.search("fashion"))).url
    pages = provider.fetch([good, "https://not-a-real-page.invalid/x"])
    assert len(pages) == 1
    assert pages[0].url == good


def test_fetch_of_nothing_is_not_an_error() -> None:
    assert MockSearchProvider().fetch([]) == []


# --------------------------------------------------------------------------
# LLM
# --------------------------------------------------------------------------


def test_llm_requests_a_tool_when_tools_are_offered() -> None:
    tool = ToolSpec(name="search", description="search the web", parameters={"type": "object"})
    response = MockLLMProvider().generate([Message(role="user", text="find leads")], tools=[tool])
    assert response.wants_tools
    assert response.tool_calls[0].name == "search"


def test_llm_overload_is_deterministic() -> None:
    """Seeded so a failing case fails identically on every run."""
    provider = MockLLMProvider(unavailable_rate=1.0)
    with pytest.raises(ProviderUnavailableError):
        provider.generate([Message(role="user", text="anything")])


def test_llm_never_fails_when_the_rate_is_zero() -> None:
    provider = MockLLMProvider(unavailable_rate=0.0)
    for index in range(20):
        assert provider.generate([Message(role="user", text=str(index))]).model


# --------------------------------------------------------------------------
# Email
# --------------------------------------------------------------------------


def _send(provider: MockEmailProvider, to: str):
    return provider.send(
        to=to,
        subject="Hello",
        html="<p>Hi</p>",
        text="Hi",
        from_name="StyleSense AI",
        from_address="onboarding@resend.dev",
    )


def test_successful_send_is_captured_with_a_message_id() -> None:
    provider = MockEmailProvider()
    result = _send(provider, "someone@example.com")
    assert result.provider_message_id
    assert len(provider.sent) == 1


@pytest.mark.parametrize("address", ["not-an-email", "trailing@", "has space@example.com"])
def test_malformed_recipients_are_rejected(address: str) -> None:
    with pytest.raises(ProviderError):
        _send(MockEmailProvider(), address)


def test_hard_bounce_is_surfaced_as_a_provider_error() -> None:
    with pytest.raises(ProviderError, match="hard bounce"):
        _send(MockEmailProvider(), "bounce@example.com")


def test_oversized_message_is_rejected() -> None:
    provider = MockEmailProvider()
    with pytest.raises(ProviderError, match="oversized"):
        provider.send(
            to="someone@example.com",
            subject="Big",
            html="x" * (MockEmailProvider.MAX_BYTES + 1),
            text="Big",
            from_name="StyleSense AI",
            from_address="onboarding@resend.dev",
        )


def test_a_rejected_send_is_not_recorded_as_sent() -> None:
    provider = MockEmailProvider()
    with pytest.raises(ProviderError):
        _send(provider, "bounce@example.com")
    assert provider.sent == []
