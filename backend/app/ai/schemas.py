"""Structured output contracts for the discovery agent.

The model never writes to the database. It produces JSON against the schema
below, which is then validated twice — once by Pydantic for shape, once by
`app.ai.validation` for business rules — before anything is persisted.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class ExtractedLead(BaseModel):
    """One candidate person, as returned by the model."""

    first_name: str = Field(min_length=1, max_length=120)
    last_name: str | None = Field(default=None, max_length=120)
    job_title: str = Field(min_length=2, max_length=200)
    email: str | None = None
    linkedin_url: str | None = None

    #: The page this person was found on. Validated against the set of URLs the
    #: agent actually visited — a citation the agent did not read is a
    #: fabrication, however plausible it looks.
    source_url: str = Field(min_length=8)

    company_name: str = Field(min_length=2, max_length=255)
    company_domain: str | None = None
    company_industry: str | None = None
    company_region: str | None = None
    company_country: str | None = None
    company_employee_count: int | None = Field(default=None, ge=0, le=10_000_000)
    company_description: str | None = None

    #: A specific, dated fact about the company — a launch, a hiring push, a
    #: funding round. This is what fills `observed_signal_sentence` in the
    #: outreach template, so it is captured with its own citation rather than
    #: being re-invented at send time.
    observed_signal: str | None = Field(default=None, max_length=500)
    signal_source_url: str | None = None

    @field_validator("email")
    @classmethod
    def _normalise_email(cls, value: str | None) -> str | None:
        if not value:
            return None
        cleaned = value.strip().lower()
        return cleaned or None

    @field_validator("first_name", "last_name", "job_title", "company_name")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return value.strip() if value else value


class ExtractionResult(BaseModel):
    leads: list[ExtractedLead] = Field(default_factory=list)


#: Gemini's `responseSchema` accepts an OpenAPI subset — `nullable` rather than
#: `anyOf`, and no `$ref`. Written out by hand for that reason.
EXTRACTION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "leads": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "first_name": {"type": "string"},
                    "last_name": {"type": "string", "nullable": True},
                    "job_title": {"type": "string"},
                    "email": {"type": "string", "nullable": True},
                    "linkedin_url": {"type": "string", "nullable": True},
                    "source_url": {
                        "type": "string",
                        "description": "A URL you actually opened. Never invent one.",
                    },
                    "company_name": {"type": "string"},
                    "company_domain": {"type": "string", "nullable": True},
                    "company_industry": {"type": "string", "nullable": True},
                    "company_region": {"type": "string", "nullable": True},
                    "company_country": {"type": "string", "nullable": True},
                    "company_employee_count": {"type": "integer", "nullable": True},
                    "company_description": {"type": "string", "nullable": True},
                    "observed_signal": {
                        "type": "string",
                        "nullable": True,
                        "description": (
                            "A specific, verifiable fact stated on the page: a launch, "
                            "expansion, funding round, or open role. Omit if the page "
                            "does not state one."
                        ),
                    },
                    "signal_source_url": {"type": "string", "nullable": True},
                },
                "required": ["first_name", "job_title", "source_url", "company_name"],
            },
        }
    },
    "required": ["leads"],
}
