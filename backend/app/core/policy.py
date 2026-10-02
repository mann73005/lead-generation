"""Loaders for the YAML policy files.

Three config files drive behaviour that would otherwise be literals in the
source: `scoring.yaml` (loaded by the scoring engine), `discovery.yaml` and
`product.yaml`. All are validated on load, so a typo fails at startup with a
field name rather than halfway through a discovery run.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator

from app.core.config import BACKEND_DIR

CONFIG_DIR = BACKEND_DIR / "config"


def _read(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


# --------------------------------------------------------------------------
# discovery.yaml
# --------------------------------------------------------------------------


class DiscoveryLimits(BaseModel):
    seed_fetch_count: int = Field(ge=1, le=20)
    refinement_turns: int = Field(ge=0, le=10)
    max_searches: int = Field(ge=1, le=30)
    max_fetches: int = Field(ge=1, le=50)
    page_char_budget: int = Field(ge=500, le=50_000)
    searches_before_fetch_forced: int = Field(ge=1, le=10)


class DiscoverySources(BaseModel):
    gated_domains: list[str] = Field(min_length=1)
    job_path_markers: list[str] = Field(default_factory=list)


class SeedQueries(BaseModel):
    per_title: str
    max_titles: int = Field(ge=0, le=10)
    global_: list[str] = Field(alias="global", default_factory=list)
    with_keywords: str | None = None
    max_queries: int = Field(ge=1, le=15)

    @model_validator(mode="after")
    def _templates_must_use_their_placeholders(self) -> "SeedQueries":
        if "{title}" not in self.per_title:
            raise ValueError("seed_queries.per_title must contain {title}")
        return self


class DiscoveryValidation(BaseModel):
    role_mailboxes: list[str]
    placeholder_names: list[str]
    vague_titles: list[str]
    non_buyer_title_markers: list[str]


class DiscoveryPrompts(BaseModel):
    system: str
    extraction: str

    @model_validator(mode="after")
    def _extraction_must_accept_a_limit(self) -> "DiscoveryPrompts":
        if "{limit}" not in self.extraction:
            raise ValueError("prompts.extraction must contain {limit}")
        return self


class DiscoveryPolicy(BaseModel):
    version: int
    limits: DiscoveryLimits
    sources: DiscoverySources
    seed_queries: SeedQueries
    validation: DiscoveryValidation
    prompts: DiscoveryPrompts

    # Pre-lowercased sets, built once rather than on every candidate.
    @property
    def role_mailbox_set(self) -> frozenset[str]:
        return frozenset(v.lower() for v in self.validation.role_mailboxes)

    @property
    def placeholder_name_set(self) -> frozenset[str]:
        return frozenset(v.lower() for v in self.validation.placeholder_names)

    @property
    def vague_title_set(self) -> frozenset[str]:
        return frozenset(v.lower() for v in self.validation.vague_titles)


# --------------------------------------------------------------------------
# product.yaml
# --------------------------------------------------------------------------


class ProductIdentity(BaseModel):
    name: str
    description: str
    segments: dict[str, Any]

    def segment_for(self, text: str | None) -> str:
        """Pick {{company_segment}} from whatever the company describes itself as."""
        mapping: dict[str, str] = self.segments.get("by_keyword", {})
        haystack = (text or "").lower()
        for keyword, segment in mapping.items():
            if keyword.lower() in haystack:
                return segment
        return str(self.segments.get("default", "retail"))


class PainPoint(BaseModel):
    label: str
    capability: str
    #: Matched against the stored evidence about the company.
    signals: list[str] = Field(default_factory=list)
    #: Matched against the lead's own job title — their remit is evidence of
    #: which problem belongs to them.
    title_signals: list[str] = Field(default_factory=list)


class TemplateSentence(BaseModel):
    id: str
    text: str
    required: list[str] = Field(default_factory=list)
    optional: bool = False


class OptionalToken(BaseModel):
    #: Connecting punctuation rendered only when the token has a value.
    prefix: str = ""


class OutreachTemplate(BaseModel):
    subject_options: list[str] = Field(min_length=1)
    body: list[TemplateSentence] = Field(min_length=1)
    optional_tokens: dict[str, OptionalToken] = Field(default_factory=dict)

    @property
    def optional_token_set(self) -> frozenset[str]:
        return frozenset(self.optional_tokens)

    @model_validator(mode="after")
    def _template_is_internally_consistent(self) -> "OutreachTemplate":
        """Checked on the template itself, not on its container.

        That placement matters: it means a template posted to the API fails
        request validation with a field-level 422, rather than being accepted
        and then failing later when someone tries to mail a lead.
        """
        required = {token for sentence in self.body for token in sentence.required}

        clash = required & set(self.optional_tokens)
        if clash:
            # Both droppable and mandatory at once: the sentence could neither
            # be dropped nor rendered without the token.
            raise ValueError(f"tokens listed as optional but also required: {sorted(clash)}")

        for sentence in self.body:
            for token in sentence.required:
                if f"{{{{{token}}}}}" not in sentence.text:
                    raise ValueError(
                        f"sentence {sentence.id!r} requires {token!r} but does not contain it"
                    )
        return self


class ProductConfig(BaseModel):
    version: int
    identity: ProductIdentity
    pain_points: dict[str, PainPoint]
    #: Fallback pain point when neither the evidence nor the title matches.
    default: str | None = None
    research_signals: list[list[str]] = Field(default_factory=list)
    template: OutreachTemplate

    @model_validator(mode="after")
    def _default_pain_point_exists(self) -> "ProductConfig":
        if self.default and self.default not in self.pain_points:
            raise ValueError(f"default pain point {self.default!r} is not defined")
        return self


# --------------------------------------------------------------------------
# Accessors
# --------------------------------------------------------------------------


@lru_cache(maxsize=1)
def load_discovery_policy(path: Path | None = None) -> DiscoveryPolicy:
    return DiscoveryPolicy.model_validate(_read(path or CONFIG_DIR / "discovery.yaml"))


@lru_cache(maxsize=1)
def load_product_config(path: Path | None = None) -> ProductConfig:
    return ProductConfig.model_validate(_read(path or CONFIG_DIR / "product.yaml"))
