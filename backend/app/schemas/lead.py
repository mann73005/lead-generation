"""Lead payloads.

`LeadOut` is shaped for the console's ranked table — company and score are
flattened in so the list view needs one request, not N+1.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.enums import LeadStatus


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    domain: str | None
    industry: str | None
    region: str | None
    country: str | None
    employee_count: int | None
    source_url: str


class ScoreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total_score: int
    fit_score: int
    engagement_score: int
    status: LeadStatus
    breakdown: dict[str, Any]
    computed_at: datetime


class ScoreHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    old_score: int | None
    new_score: int
    delta: int
    reason: str
    created_at: datetime


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_type: str
    occurred_at: datetime
    campaign_id: UUID | None
    message_id: UUID | None
    event_metadata: dict[str, Any] = Field(serialization_alias="metadata")


class LeadBase(BaseModel):
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str | None = Field(default=None, max_length=120)
    job_title: str = Field(min_length=2, max_length=200)
    email: EmailStr | None = None
    linkedin_url: str | None = None
    seniority: str | None = Field(default=None, max_length=60)

    @field_validator("email")
    @classmethod
    def _lowercase(cls, value: str | None) -> str | None:
        return value.lower().strip() if value else None


class LeadCreate(LeadBase):
    company_id: UUID
    source_url: str = Field(min_length=8, description="Page this lead was found on.")


class LeadUpdate(BaseModel):
    """Every field optional — PATCH semantics."""

    first_name: str | None = Field(default=None, min_length=1, max_length=120)
    last_name: str | None = Field(default=None, max_length=120)
    job_title: str | None = Field(default=None, min_length=2, max_length=200)
    email: EmailStr | None = None
    linkedin_url: str | None = None
    seniority: str | None = Field(default=None, max_length=60)


class LeadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    first_name: str
    last_name: str | None
    full_name: str
    job_title: str
    email: str | None
    linkedin_url: str | None
    source_url: str
    created_at: datetime
    company: CompanyOut
    score: ScoreOut | None


class LeadDetailOut(LeadOut):
    """Everything the lead drawer needs, in one request."""

    events: list[EventOut]
    score_history: list[ScoreHistoryOut]
