"""Provider contracts.

Everything the application needs from the outside world — web search, page
fetching, an LLM, an email gateway — is expressed here as a Protocol with
vendor-neutral types. Business logic imports these, never a vendor SDK, so a
provider can be swapped or mocked without touching a service.

The message types are deliberately not Gemini's wire format. Translating at the
provider boundary costs about forty lines and is the difference between an
abstraction and a rename.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

# --------------------------------------------------------------------------
# Search and fetch
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    score: float | None = None


@dataclass(frozen=True)
class FetchedPage:
    url: str
    content: str
    title: str | None = None
    truncated: bool = False


@runtime_checkable
class SearchProvider(Protocol):
    name: str

    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        """Return ranked results. An empty list is a valid answer, not an error."""
        ...


@runtime_checkable
class FetchProvider(Protocol):
    name: str

    def fetch(self, urls: list[str], *, max_chars: int = 20_000) -> list[FetchedPage]:
        """Fetch readable page text.

        Unreachable URLs are omitted rather than raising: one dead link in a
        batch of five must not abandon the other four.
        """
        ...


# --------------------------------------------------------------------------
# LLM
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    #: JSON Schema for the arguments object.
    parameters: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

    #: Opaque provider state that must be round-tripped verbatim on the next
    #: turn. Gemini's thinking models reject a conversation whose function-call
    #: parts come back without their `thoughtSignature`. Callers never read
    #: this; they only hand the ToolCall back unmodified.
    provider_state: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    name: str
    content: Any


@dataclass
class Message:
    role: Literal["user", "model", "tool"]
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)


@dataclass(frozen=True)
class LLMResponse:
    text: str
    tool_calls: list[ToolCall]
    model: str
    #: Prompt/response token counts when the provider reports them.
    usage: dict[str, int] = field(default_factory=dict)

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    def generate(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        tools: list[ToolSpec] | None = None,
        json_schema: dict[str, Any] | None = None,
        temperature: float = 0.2,
    ) -> LLMResponse:
        """One turn of a conversation.

        `json_schema` and `tools` are mutually exclusive in practice: a model
        asked for structured output should not also be choosing tools.
        """
        ...


# --------------------------------------------------------------------------
# Email
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SentMessage:
    provider_message_id: str
    to: str
    provider: str


@runtime_checkable
class EmailProvider(Protocol):
    name: str

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
        """Hand a message to the gateway. Raises ProviderError on failure."""
        ...
