"""Event ingestion payloads."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import EmailEventType


class EventCreate(BaseModel):
    """Manual event ingestion.

    Exists so the lifecycle can be driven end-to-end in a demo without waiting
    on a real mail client — and so provider webhooks have a shape to post into
    later. `occurred_at` is accepted from the caller because an event can be
    reported after the fact.
    """

    lead_id: UUID
    event_type: EmailEventType
    campaign_id: UUID | None = None
    message_id: UUID | None = None
    occurred_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
