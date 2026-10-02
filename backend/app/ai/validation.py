"""Business validation for extracted leads.

Pydantic has already checked that the model returned the right *shape*. This
module checks whether what it returned is *believable*, and is the reason the
agent cannot write arbitrary rows: nothing reaches the database without
surviving every rule here.

The rules themselves — which mailboxes are shared, which titles hold no budget,
which names are placeholders — live in `config/discovery.yaml`, not in this
file. They are judgement calls that get retuned as you learn what the open web
actually returns.

Rules are split by severity.

  REJECT  the candidate is discarded — a fabricated citation or a placeholder
          person is not a lead with a data-quality problem, it is not a lead.
  STRIP   the candidate survives but a field is dropped — a role mailbox is a
          real address that simply is not a person's.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from app.ai.schemas import ExtractedLead
from app.core.policy import DiscoveryPolicy, load_discovery_policy

_EMAIL_SHAPE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.IGNORECASE)


@dataclass(frozen=True)
class Rejection:
    lead: str
    reason: str
    detail: str


@dataclass
class ValidationOutcome:
    accepted: list[ExtractedLead]
    rejections: list[Rejection]
    #: Field-level removals that did not cost the lead its place.
    strips: list[Rejection]


def _normalise_url(url: str) -> str:
    """Compare URLs without tripping over a trailing slash, www or a query."""
    try:
        parsed = urlparse(url.strip().lower())
    except ValueError:
        return url.strip().lower()
    host = parsed.netloc.removeprefix("www.")
    return f"{host}{parsed.path.rstrip('/')}"


def _is_placeholder(value: str | None, placeholders: frozenset[str]) -> bool:
    if not value:
        return True
    cleaned = value.strip().lower()
    return (
        cleaned in placeholders
        or len(cleaned) < 2
        or bool(re.fullmatch(r"[\W\d_]+", cleaned))
    )


def validate_candidates(
    candidates: list[ExtractedLead],
    *,
    visited_urls: set[str],
    policy: DiscoveryPolicy | None = None,
) -> ValidationOutcome:
    """Filter model output down to leads worth storing."""
    policy = policy or load_discovery_policy()
    placeholders = policy.placeholder_name_set
    role_mailboxes = policy.role_mailbox_set
    vague_titles = policy.vague_title_set
    non_buyer_markers = [m.lower() for m in policy.validation.non_buyer_title_markers]

    visited = {_normalise_url(u) for u in visited_urls}
    accepted: list[ExtractedLead] = []
    rejections: list[Rejection] = []
    strips: list[Rejection] = []
    seen: set[tuple[str, str]] = set()

    for candidate in candidates:
        label = f"{candidate.first_name} {candidate.last_name or ''} @ {candidate.company_name}".strip()

        # 1. The citation must point at a page the agent actually opened.
        if _normalise_url(candidate.source_url) not in visited:
            rejections.append(
                Rejection(label, "unvisited_source_url", f"{candidate.source_url} was never fetched")
            )
            continue

        if _is_placeholder(candidate.first_name, placeholders):
            rejections.append(Rejection(label, "placeholder_name", candidate.first_name))
            continue

        title_lower = candidate.job_title.strip().lower()
        if _is_placeholder(candidate.job_title, placeholders) or title_lower in vague_titles:
            rejections.append(Rejection(label, "vague_job_title", candidate.job_title))
            continue

        marker = next((m for m in non_buyer_markers if m in title_lower), None)
        if marker:
            rejections.append(Rejection(label, "not_a_buying_role", f"title contains {marker!r}"))
            continue

        if _is_placeholder(candidate.company_name, placeholders):
            rejections.append(Rejection(label, "placeholder_company", candidate.company_name))
            continue

        # 2. Two rows for the same person at the same company help nobody.
        key = (candidate.first_name.lower(), candidate.company_name.lower())
        if key in seen:
            rejections.append(Rejection(label, "duplicate_in_batch", "already extracted in this run"))
            continue
        seen.add(key)

        # 3. Field-level cleanup — the lead survives, the bad value does not.
        if candidate.email:
            local = candidate.email.split("@", 1)[0]
            if not _EMAIL_SHAPE.match(candidate.email):
                strips.append(Rejection(label, "malformed_email", candidate.email))
                candidate.email = None
            elif local in role_mailboxes:
                strips.append(Rejection(label, "role_mailbox", candidate.email))
                candidate.email = None

        if candidate.linkedin_url and "linkedin.com" not in candidate.linkedin_url.lower():
            strips.append(Rejection(label, "not_a_linkedin_url", candidate.linkedin_url))
            candidate.linkedin_url = None

        # 4. A signal is only usable if its own citation was read. Dropping the
        #    signal rather than the lead keeps a good contact whose
        #    personalisation hook happens to be unverifiable.
        if candidate.observed_signal:
            signal_url = candidate.signal_source_url or candidate.source_url
            if _normalise_url(signal_url) not in visited:
                strips.append(
                    Rejection(label, "ungrounded_signal", f"{signal_url} was never fetched")
                )
                candidate.observed_signal = None
                candidate.signal_source_url = None
            else:
                candidate.signal_source_url = signal_url

        accepted.append(candidate)

    return ValidationOutcome(accepted=accepted, rejections=rejections, strips=strips)
