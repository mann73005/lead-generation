"""Lead scoring.

The engine is a pure function of (lead, company, icp, events, reply intent).
It holds no state, touches no database and reads no module-level constants —
every number comes from `config/scoring.yaml`. That is what makes the brief's
"recompute from history" requirement real rather than aspirational: delete
every row in `lead_scores`, replay the events, and you get identical numbers.

Scores are always recomputed in full. Nothing in this module increments an
existing score, because an incremental update cannot be replayed and silently
drifts once a weight changes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import yaml
from pydantic import BaseModel, Field, model_validator

from app.core.config import settings
from app.models.enums import EVENT_TO_STATUS, LEAD_STATUS_RANK, EmailEventType, LeadStatus

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


class FitWeights(BaseModel):
    industry_match: int
    region_match: int
    company_size_match: int
    title_exact_match: int
    title_partial_match: int
    has_email: int
    has_linkedin: int


class FitConfig(BaseModel):
    max: int
    weights: FitWeights


class EngagementWeights(BaseModel):
    delivered: int
    opened: int
    replied: int


class EngagementConfig(BaseModel):
    max: int
    weights: EngagementWeights
    repeat_open_bonus: int
    max_repeat_open_bonus: int
    reply_intent: dict[str, int]


class PenaltyConfig(BaseModel):
    unsubscribed: int
    bounced: int


class BandConfig(BaseModel):
    hot: int
    warm: int
    cold: int


class ScoringConfig(BaseModel):
    version: int
    fit: FitConfig
    engagement: EngagementConfig
    penalties: PenaltyConfig
    bands: BandConfig

    @model_validator(mode="after")
    def _ceilings_must_be_reachable(self) -> "ScoringConfig":
        """Catch a miswritten config at load time rather than at scoring time.

        A `max` below the sum of its weights is legal (it just means the
        component saturates), but a `max` of zero or a negative weight almost
        certainly means someone fat-fingered the YAML.
        """
        if self.fit.max <= 0 or self.engagement.max <= 0:
            raise ValueError("fit.max and engagement.max must be positive")
        if self.fit.max + self.engagement.max > 100:
            raise ValueError(
                f"fit.max ({self.fit.max}) + engagement.max ({self.engagement.max}) "
                "exceeds 100; the total would clamp and compress the ranking"
            )
        return self


@lru_cache(maxsize=1)
def load_scoring_config(path: Path | None = None) -> ScoringConfig:
    """Read and validate the scoring weights. Cached for the process lifetime."""
    config_path = path or settings.scoring_config_path
    with open(config_path, encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    return ScoringConfig.model_validate(raw)


# --------------------------------------------------------------------------
# Result
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ScoreResult:
    fit_score: int
    engagement_score: int
    total_score: int
    status: LeadStatus
    breakdown: dict[str, Any] = field(default_factory=dict)

    @property
    def band(self) -> str:
        return str(self.breakdown.get("band", "cold"))


# --------------------------------------------------------------------------
# Title matching
# --------------------------------------------------------------------------

_PUNCTUATION = re.compile(r"[^a-z0-9\s]")
_WHITESPACE = re.compile(r"\s+")

#: Words that appear in almost every target title and therefore carry no
#: signal on their own — "Head of Supply Chain" and "Head of Marketing" must
#: not count as a partial match just because both say "head".
_TITLE_STOPWORDS = frozenset(
    {
        "head", "of", "the", "and", "director", "vp", "vice", "president",
        "manager", "lead", "senior", "sr", "junior", "jr", "chief", "officer",
        "global", "regional", "group", "general", "deputy", "assistant",
    }
)


def _normalise(value: str) -> str:
    return _WHITESPACE.sub(" ", _PUNCTUATION.sub(" ", value.lower())).strip()


def _content_words(value: str) -> set[str]:
    return {w for w in _normalise(value).split() if w not in _TITLE_STOPWORDS and len(w) > 2}


def match_title(job_title: str | None, target_titles: Iterable[str]) -> str | None:
    """Classify a job title against the ICP's target titles.

    Returns "exact", "partial" or None.

    "exact"   the full target title appears in the job title, so
              "Head of Merchandising" matches "Head of Merchandising, India".
    "partial" the distinguishing words overlap but the phrase does not, so
              "Merchandising Manager" is a weaker match for the same target.
    """
    if not job_title:
        return None

    normalised_title = _normalise(job_title)
    if not normalised_title:
        return None

    targets = [t for t in target_titles if t and t.strip()]
    if any(_normalise(t) in normalised_title for t in targets):
        return "exact"

    title_words = _content_words(job_title)
    if any(_content_words(t) & title_words for t in targets):
        return "partial"

    return None


def _text_matches(actual: str | None, expected: str | None) -> bool:
    """Loose containment match for industry and region.

    Discovery returns free text ("Fashion & Apparel Retail" against an ICP of
    "Fashion"), so exact equality would reject almost every real company.
    """
    if not actual or not expected:
        return False
    a, e = _normalise(actual), _normalise(expected)
    return bool(a) and bool(e) and (e in a or a in e)


# --------------------------------------------------------------------------
# Engine
# --------------------------------------------------------------------------


def compute_fit(lead: Any, company: Any, icp: Any, config: ScoringConfig) -> tuple[int, dict[str, int]]:
    """Static quality of the lead: how well it matches the ICP."""
    weights = config.fit.weights
    detail: dict[str, int] = {}

    # The ICP-relative components are only meaningful when there is an ICP to
    # compare against. Without one, "matches the target industry" is not false
    # — it is unanswerable — so no points are awarded either way.
    if icp is not None:
        if _text_matches(getattr(company, "industry", None), icp.industry):
            detail["industry_match"] = weights.industry_match

        if _text_matches(getattr(company, "region", None), icp.region) or _text_matches(
            getattr(company, "country", None), icp.region
        ):
            detail["region_match"] = weights.region_match

        size = getattr(company, "employee_count", None)
        low, high = icp.employee_min, icp.employee_max
        # An unbounded band is not a match, it is an absent criterion. Treating
        # it as a match would hand every company the size points for free.
        if size is not None and (low is not None or high is not None):
            if (low is None or size >= low) and (high is None or size <= high):
                detail["company_size_match"] = weights.company_size_match

        match = match_title(getattr(lead, "job_title", None), icp.titles or [])
        if match == "exact":
            detail["title_exact_match"] = weights.title_exact_match
        elif match == "partial":
            detail["title_partial_match"] = weights.title_partial_match

    # Contactability is a property of the lead record, not of the ICP, so it
    # still counts for a lead that has not been tied to one.
    if getattr(lead, "email", None):
        detail["has_email"] = weights.has_email
    if getattr(lead, "linkedin_url", None):
        detail["has_linkedin"] = weights.has_linkedin

    return min(sum(detail.values()), config.fit.max), detail


def compute_engagement(
    events: Iterable[Any],
    reply_intent: str | None,
    config: ScoringConfig,
) -> tuple[int, dict[str, int]]:
    """Behavioural signal: what the lead actually did with the email."""
    weights = config.engagement.weights
    detail: dict[str, int] = {}

    types = [str(getattr(e, "event_type", e)) for e in events]
    counts = {t: types.count(t) for t in set(types)}

    if counts.get(EmailEventType.DELIVERED):
        detail["delivered"] = weights.delivered

    opens = counts.get(EmailEventType.OPENED, 0)
    if opens:
        detail["opened"] = weights.opened
        if opens > 1:
            detail["repeat_opens"] = min(
                (opens - 1) * config.engagement.repeat_open_bonus,
                config.engagement.max_repeat_open_bonus,
            )

    if counts.get(EmailEventType.REPLIED):
        detail["replied"] = weights.replied
        if reply_intent and reply_intent in config.engagement.reply_intent:
            detail[f"intent_{reply_intent}"] = config.engagement.reply_intent[reply_intent]

    # Clamped at both ends: a negative intent modifier must not drag the
    # engagement component below zero and start eating into the fit score.
    total = max(0, min(sum(detail.values()), config.engagement.max))
    return total, detail


def derive_status(events: Iterable[Any]) -> LeadStatus:
    """Highest-ranked lifecycle status implied by the lead's events."""
    status = LeadStatus.NEW
    for event in events:
        raw = str(getattr(event, "event_type", event))
        try:
            implied = EVENT_TO_STATUS[EmailEventType(raw)]
        except (ValueError, KeyError):
            continue
        if LEAD_STATUS_RANK[implied] > LEAD_STATUS_RANK[status]:
            status = implied
    return status


def compute_score(
    lead: Any,
    company: Any,
    icp: Any,
    events: Iterable[Any] | None = None,
    reply_intent: str | None = None,
    config: ScoringConfig | None = None,
) -> ScoreResult:
    """Full score for one lead. Deterministic and side-effect free."""
    config = config or load_scoring_config()
    events = list(events or [])

    fit, fit_detail = compute_fit(lead, company, icp, config)
    engagement, engagement_detail = compute_engagement(events, reply_intent, config)
    status = derive_status(events)

    total = fit + engagement
    applied_penalty: str | None = None

    # Compliance and deliverability override merit: an opted-out lead is not
    # workable no matter how well it fits, so the cap is applied last.
    if status is LeadStatus.UNSUBSCRIBED:
        total = min(total, config.penalties.unsubscribed)
        applied_penalty = "unsubscribed"
    elif status is LeadStatus.BOUNCED:
        total = min(total, config.penalties.bounced)
        applied_penalty = "bounced"

    total = max(0, min(total, 100))

    bands = config.bands
    band = "hot" if total >= bands.hot else "warm" if total >= bands.warm else "cold"

    return ScoreResult(
        fit_score=fit,
        engagement_score=engagement,
        total_score=total,
        status=status,
        breakdown={
            "fit": fit_detail,
            "engagement": engagement_detail,
            "fit_total": fit,
            "engagement_total": engagement,
            "penalty": applied_penalty,
            "band": band,
            "config_version": config.version,
        },
    )
