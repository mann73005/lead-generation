"""Resend email provider."""

from __future__ import annotations

from app.core.config import settings
from app.core.exceptions import ProviderError, ProviderNotConfiguredError
from app.core.logging import get_logger
from app.providers.base import SentMessage
from app.providers.http import post_json

logger = get_logger(__name__)

SEND_URL = "https://api.resend.com/emails"


class ResendProvider:
    name = "resend"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or settings.resend_api_key
        if not self._api_key:
            raise ProviderNotConfiguredError(
                "RESEND_API_KEY is not set, so outreach cannot be sent",
                details={"provider": self.name},
            )

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
        body = post_json(
            SEND_URL,
            {
                "from": f"{from_name} <{from_address}>",
                "to": [to],
                "subject": subject,
                "html": html,
                "text": text,
                "headers": headers or {},
            },
            provider=self.name,
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=45.0,
            # Not retried: a send that times out may still have been accepted,
            # and a duplicate cold email is worse than a reported failure.
            attempts=1,
        )

        message_id = body.get("id")
        if not message_id:
            raise ProviderError(
                "Resend accepted the request but returned no message id",
                details={"provider": self.name, "body": str(body)[:300]},
            )

        logger.info("resend accepted message %s for %s", message_id, to)
        return SentMessage(provider_message_id=message_id, to=to, provider=self.name)
