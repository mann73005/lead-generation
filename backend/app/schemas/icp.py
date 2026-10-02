"""ICP definition payloads."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ICPCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    industry: str = Field(min_length=2, max_length=120)
    region: str = Field(min_length=2, max_length=120)
    employee_min: int | None = Field(default=None, ge=0)
    employee_max: int | None = Field(default=None, ge=0)
    titles: list[str] = Field(min_length=1, max_length=10)
    keywords: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def _check(self) -> "ICPCreate":
        if self.employee_min is not None and self.employee_max is not None:
            if self.employee_min > self.employee_max:
                raise ValueError("employee_min must not exceed employee_max")
        cleaned = [t.strip() for t in self.titles if t.strip()]
        if not cleaned:
            raise ValueError("titles must contain at least one non-empty value")
        self.titles = cleaned
        self.keywords = [k.strip() for k in self.keywords if k.strip()]
        return self


class ICPOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    industry: str
    region: str
    employee_min: int | None
    employee_max: int | None
    titles: list[str]
    keywords: list[str]
    created_at: datetime


class DiscoveryRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    icp_id: UUID
    status: str
    requested_count: int
    companies_created: int
    leads_created: int
    leads_rejected: int
    error: str | None
    started_at: datetime | None
    completed_at: datetime | None


class DiscoveryRunDetailOut(DiscoveryRunOut):
    """Includes the tool-call transcript, so a run can be audited after the fact."""

    agent_log: dict[str, Any]
