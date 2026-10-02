"""Reply payloads."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ReplyIntent


class ReplyCreate(BaseModel):
    """A reply pasted into the console.

    Real inbound ingestion is a stretch item; this is the same shape a
    provider webhook would post, so swapping one in later changes the
    transport and not the handling.
    """

    lead_id: UUID
    text: str = Field(min_length=2, max_length=10_000)
    campaign_id: UUID | None = None
    message_id: UUID | None = None


class ReplyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    lead_id: UUID
    campaign_id: UUID | None
    raw_text: str
    intent: ReplyIntent
    confidence: float | None
    reasoning: str | None
    #: Persisted unsent. Sending requires a separate, explicit approval.
    draft_response: str | None
    classifier_model: str | None
    approved: bool
    approved_at: datetime | None
    created_at: datetime


class ReplyApproval(BaseModel):
    #: Lets the salesperson edit the draft before approving it.
    draft_response: str | None = Field(default=None, max_length=10_000)
