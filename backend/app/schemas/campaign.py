"""Campaign and message payloads."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.enums import CampaignStatus, MessageStatus


class CampaignCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    description: str | None = None
    icp_id: UUID | None = None
    sender_name: str = Field(min_length=2, max_length=120)
    sender_email: EmailStr


class CampaignUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = None
    status: CampaignStatus | None = None


class CampaignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    icp_id: UUID | None
    status: CampaignStatus
    sender_name: str
    sender_email: str
    created_at: datetime


class CampaignStatsOut(CampaignOut):
    lead_count: int
    sent_count: int
    opened_count: int
    replied_count: int


class AddLeadsRequest(BaseModel):
    lead_ids: list[UUID] = Field(min_length=1, max_length=200)


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    subject: str
    body_text: str
    status: MessageStatus
    to_address: str | None
    sent_at: datetime | None
    error: str | None
    #: Token -> provenance. This is what makes a generated email auditable.
    tokens: dict[str, Any]
    grounding_report: dict[str, Any]
    dropped_sentences: list[str]
