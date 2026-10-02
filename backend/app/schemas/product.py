"""Product profile payloads.

The console edits these at runtime, so the update schema is permissive about
*which* fields arrive and strict about what they contain — a malformed template
posted from the UI must fail here, not when an email is generated for a lead.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.policy import OutreachTemplate, PainPoint


class ProductProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str
    sender_name: str
    sender_email: str
    segments: dict[str, Any]
    pain_points: dict[str, Any]
    research_signals: list[Any]
    template: dict[str, Any]
    updated_at: datetime


class ProductProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, min_length=10)
    sender_name: str | None = Field(default=None, min_length=2, max_length=120)
    sender_email: EmailStr | None = None
    segments: dict[str, Any] | None = None
    pain_points: dict[str, PainPoint] | None = None
    research_signals: list[list[str]] | None = None
    template: OutreachTemplate | None = None

    @field_validator("pain_points")
    @classmethod
    def _at_least_one_pain_point(
        cls, value: dict[str, PainPoint] | None
    ) -> dict[str, PainPoint] | None:
        if value is not None and not value:
            raise ValueError("at least one pain point is required")
        return value

    def as_columns(self) -> dict[str, Any]:
        """Flatten to column values, unwrapping the nested models to JSON."""
        data = self.model_dump(exclude_unset=True, mode="json")
        return data
