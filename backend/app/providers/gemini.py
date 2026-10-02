"""Gemini LLM provider.

Translates the neutral `Message`/`ToolSpec` types onto Gemini's `contents` and
`functionDeclarations` wire format, and walks a fallback chain of models: the
newest flash models intermittently return 503 under load, and a discovery run
should degrade to an older model rather than fail outright.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from app.core.config import settings
from app.core.exceptions import (
    ProviderError,
    ProviderNotConfiguredError,
    ProviderUnavailableError,
    RateLimitedError,
)
from app.core.logging import get_logger
from app.providers.base import LLMResponse, Message, ToolCall, ToolSpec
from app.providers.http import post_json

logger = get_logger(__name__)

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


def _to_contents(messages: list[Message]) -> list[dict[str, Any]]:
    """Neutral messages -> Gemini `contents`."""
    contents: list[dict[str, Any]] = []

    for message in messages:
        parts: list[dict[str, Any]] = []

        if message.text:
            parts.append({"text": message.text})

        for call in message.tool_calls:
            part: dict[str, Any] = {"functionCall": {"name": call.name, "args": call.arguments}}
            if call.id:
                part["functionCall"]["id"] = call.id
            # Echoed verbatim beside the call. Without it the API rejects the
            # whole request with "Function call is missing a thought_signature".
            part.update(call.provider_state)
            parts.append(part)

        for result in message.tool_results:
            parts.append(
                {"functionResponse": {"name": result.name, "response": {"result": result.content}}}
            )

        if not parts:
            continue

        # Gemini has no "tool" role; tool output is returned as a user turn.
        role = "model" if message.role == "model" else "user"
        contents.append({"role": role, "parts": parts})

    return contents


def _to_declarations(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "functionDeclarations": [
                {"name": t.name, "description": t.description, "parameters": t.parameters}
                for t in tools
            ]
        }
    ]


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str | None = None, models: list[str] | None = None) -> None:
        self._api_key = api_key or settings.gemini_api_key
        if not self._api_key:
            raise ProviderNotConfiguredError(
                "GEMINI_API_KEY is not set, so the AI features cannot run",
                details={"provider": self.name},
            )
        self._models = models or settings.llm_model_chain

    def generate(
        self,
        messages: list[Message],
        *,
        system: str | None = None,
        tools: list[ToolSpec] | None = None,
        json_schema: dict[str, Any] | None = None,
        temperature: float = 0.2,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "contents": _to_contents(messages),
            "generationConfig": {"temperature": temperature},
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        if tools:
            payload["tools"] = _to_declarations(tools)
        if json_schema:
            payload["generationConfig"]["responseMimeType"] = "application/json"
            payload["generationConfig"]["responseSchema"] = json_schema

        last_error: Exception | None = None
        for model in self._models:
            try:
                body = post_json(
                    f"{BASE_URL}/{model}:generateContent",
                    payload,
                    provider=f"{self.name}:{model}",
                    params={"key": self._api_key},
                    timeout=float(settings.llm_timeout_seconds),
                    attempts=2,
                )
            except RateLimitedError as exc:
                # The free tier meters requests per day *per model*, so a model
                # that is out of quota says nothing about the next one. Moving
                # down the chain is the whole remedy here.
                last_error = exc
                logger.warning("model %s is out of daily quota, falling back", model)
                continue
            except ProviderUnavailableError as exc:
                # Overloaded (503) rather than metered — another model may have
                # capacity, so try it rather than failing the run.
                last_error = exc
                logger.warning("model %s overloaded, falling back", model)
                continue

            return self._parse(body, model)

        raise ProviderUnavailableError(
            "Every Gemini model in the fallback chain is unavailable or out of quota",
            details={"models": self._models, "last_error": str(last_error)},
        )

    def _parse(self, body: dict[str, Any], model: str) -> LLMResponse:
        candidates = body.get("candidates") or []
        if not candidates:
            # Usually a safety block; the prompt feedback explains why.
            raise ProviderError(
                "Gemini returned no candidates",
                details={"model": model, "feedback": body.get("promptFeedback", {})},
            )

        parts = candidates[0].get("content", {}).get("parts") or []
        texts: list[str] = []
        calls: list[ToolCall] = []

        for part in parts:
            if "text" in part:
                texts.append(part["text"])
            elif "functionCall" in part:
                fn = part["functionCall"]
                calls.append(
                    ToolCall(
                        # Gemini does not always supply an id; one is minted so
                        # tool results can be correlated either way.
                        id=str(fn.get("id") or uuid.uuid4()),
                        name=fn.get("name", ""),
                        arguments=fn.get("args") or {},
                        # Every sibling key of `functionCall` is carried along
                        # untouched, so a future required field needs no change
                        # here — only `thoughtSignature` matters today.
                        provider_state={k: v for k, v in part.items() if k != "functionCall"},
                    )
                )

        usage_raw = body.get("usageMetadata") or {}
        return LLMResponse(
            text="".join(texts).strip(),
            tool_calls=calls,
            model=model,
            usage={
                "prompt": usage_raw.get("promptTokenCount", 0),
                "response": usage_raw.get("candidatesTokenCount", 0),
                "total": usage_raw.get("totalTokenCount", 0),
            },
        )

    def generate_json(
        self,
        messages: list[Message],
        *,
        schema: dict[str, Any],
        system: str | None = None,
        temperature: float = 0.1,
    ) -> Any:
        """Structured output, parsed and validated as JSON.

        A model that answers with prose where JSON was demanded is a provider
        failure, not something for the caller to pattern-match out of a string.
        """
        response = self.generate(
            messages, system=system, json_schema=schema, temperature=temperature
        )
        try:
            return json.loads(response.text)
        except json.JSONDecodeError as exc:
            raise ProviderError(
                "Gemini did not return valid JSON despite a response schema",
                details={"model": response.model, "text": response.text[:400]},
            ) from exc
