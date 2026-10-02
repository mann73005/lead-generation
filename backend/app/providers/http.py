"""Shared HTTP behaviour for outbound provider calls.

Retries are deliberately narrow: only on transport errors and the two status
codes that mean "ask again later". A 400 or 401 is a bug or a bad key, and
retrying it just turns a fast failure into a slow one.
"""

from __future__ import annotations

import random
import time
from typing import Any

import httpx

from app.core.exceptions import ProviderError, ProviderUnavailableError, RateLimitedError
from app.core.logging import get_logger

logger = get_logger(__name__)

RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}

#: A per-minute limit clears on its own, so waiting is the right move.
RATE_LIMIT_BACKOFF = (6.0, 18.0, 30.0)


def _is_daily_quota(response: httpx.Response) -> bool:
    """Whether a 429 is a daily cap rather than a burst limit.

    Gemini's free tier caps requests per day, per project, *per model*. There
    is no point sleeping through that — the retryDelay comes back in hours —
    but there is every point in trying a different model, which has its own
    bucket. A per-minute limit is the opposite: same model, just wait.
    """
    try:
        body = response.json()
    except ValueError:
        return False

    for detail in body.get("error", {}).get("details", []):
        for violation in detail.get("violations", []):
            if "PerDay" in str(violation.get("quotaId", "")):
                return True
    return "per day" in body.get("error", {}).get("message", "").lower()


def _retry_delay(status: int | None, attempt: int, response: httpx.Response | None) -> float:
    if response is not None:
        header = response.headers.get("retry-after")
        if header:
            try:
                # Honour the server's own number before guessing at one.
                return min(float(header), 60.0)
            except ValueError:
                pass
    if status == 429:
        return RATE_LIMIT_BACKOFF[min(attempt - 1, len(RATE_LIMIT_BACKOFF) - 1)]
    # Exponential with jitter, so parallel calls do not retry in lockstep and
    # re-trigger the same limit.
    return (2 ** (attempt - 1)) + random.uniform(0, 0.4)


def post_json(
    url: str,
    payload: dict[str, Any],
    *,
    provider: str,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    timeout: float = 60.0,
    attempts: int = 3,
) -> dict[str, Any]:
    """POST JSON with bounded retries, returning the decoded body."""
    last_error: Exception | None = None
    last_status: int | None = None
    last_response: httpx.Response | None = None

    for attempt in range(1, attempts + 1):
        last_status, last_response = None, None
        try:
            response = httpx.post(
                url, json=payload, headers=headers, params=params, timeout=timeout
            )
        except httpx.TimeoutException as exc:
            last_error = exc
            logger.warning("%s timed out (attempt %s/%s)", provider, attempt, attempts)
        except httpx.HTTPError as exc:
            last_error = exc
            logger.warning("%s transport error: %s (attempt %s/%s)", provider, exc, attempt, attempts)
        else:
            if response.status_code < 300:
                try:
                    return response.json()
                except ValueError as exc:
                    # A 200 that is not JSON is not retryable — the endpoint is
                    # answering, just not with what the contract promises.
                    raise ProviderError(
                        f"{provider} returned a non-JSON response",
                        details={"provider": provider, "body": response.text[:300]},
                    ) from exc

            if response.status_code not in RETRYABLE_STATUS:
                raise ProviderError(
                    f"{provider} rejected the request ({response.status_code})",
                    details={
                        "provider": provider,
                        "status": response.status_code,
                        "body": response.text[:300],
                    },
                )

            if response.status_code == 429 and _is_daily_quota(response):
                # Hours away from resetting. Surface it immediately so the
                # caller can move to a model with its own quota bucket rather
                # than sleeping through a backoff that cannot possibly help.
                raise RateLimitedError(
                    f"{provider} has exhausted its daily quota",
                    details={"provider": provider, "scope": "per_day"},
                )

            last_status, last_response = response.status_code, response
            last_error = ProviderUnavailableError(
                f"{provider} is unavailable ({response.status_code})",
                details={"provider": provider, "status": response.status_code},
            )
            logger.warning(
                "%s returned %s (attempt %s/%s)", provider, response.status_code, attempt, attempts
            )

        if attempt < attempts:
            delay = _retry_delay(last_status, attempt, last_response)
            logger.info("%s retrying in %.1fs", provider, delay)
            time.sleep(delay)

    if last_status == 429:
        # Distinguished from a generic outage: a caller that falls back to
        # another model on a quota error just spends the same quota again.
        raise RateLimitedError(
            f"{provider} is rate limited", details={"provider": provider, "status": 429}
        )

    raise ProviderUnavailableError(
        f"{provider} did not respond successfully after {attempts} attempts",
        details={"provider": provider, "last_error": str(last_error)},
    )
