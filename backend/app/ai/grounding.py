"""The grounding check.

The brief asks for "one programmatic check that blocks a token being filled
with an unverifiable claim, and log when it fires". This is it.

The rule is narrow on purpose. Asking a model "is this grounded?" just moves
the trust problem one step along, so instead the check is mechanical: a filled
token may only contain *specifics* that already appear in the evidence we hold
for that lead. Specifically it rejects

  * numbers the evidence does not contain — "opened 20 new stores" when
    nothing we stored mentions 20, which is the single most common way a
    plausible sentence turns into a false one;
  * capitalised proper nouns the evidence does not contain — a brand, city or
    person the model has supplied from memory.

Ordinary prose is left alone. The check is not trying to verify that a sentence
is *true*; it verifies that every concrete thing it asserts came from a stored
field or a cited page, which is what makes the claim checkable by a human.

Evidence is assembled only from the database: company and lead columns, and the
observed signal captured at discovery time with its source URL. Nothing the
model says about itself counts as evidence for itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

#: No trailing word boundary, so a magnitude or unit suffix does not hide the
#: figure: "$40M", "18%" and "250k" all surface their number. The leading
#: boundary stays, so the "2" in "B2B" is not treated as a claim.
_NUMBER = re.compile(r"\b\d[\d,.]*")
#: One or more capitalised words not at the start of a sentence.
_PROPER_NOUN = re.compile(r"\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})*")

#: Capitalised words common enough that their presence says nothing. Without
#: this every sentence starting "Given" or naming a month would be rejected.
_COMMON_CAPITALS = frozenset(
    {
        "given", "the", "their", "they", "this", "that", "would", "with", "your",
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
        "january", "february", "march", "april", "may", "june", "july", "august",
        "september", "october", "november", "december",
        "head", "chief", "director", "manager", "officer", "president", "vice",
        "merchandising", "planning", "supply", "chain", "inventory", "demand",
        "retail", "fashion", "apparel",
    }
)


def _digits_only(value: str) -> str:
    return re.sub(r"[^\d]", "", value)


@dataclass
class Evidence:
    """Everything we are allowed to treat as established fact for one lead."""

    #: field name -> stored value, used to attribute a token to its origin.
    fields: dict[str, str] = field(default_factory=dict)
    #: URLs that back those fields.
    source_urls: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " \n".join(str(v) for v in self.fields.values() if v)

    def _haystack(self) -> str:
        return self.text.lower()

    def contains(self, needle: str) -> bool:
        return needle.lower() in self._haystack()

    def contains_number(self, number: str) -> bool:
        """Whole-number comparison, with separators normalised away.

        Substring matching is wrong for figures in both directions: "40" would
        be found inside a stored "400" and wave through a fabricated amount,
        while "1,200" would miss a stored "1200" and block a true one. Both
        sides are reduced to bare digits and compared as whole values.
        """
        target = _digits_only(number)
        if not target:
            return False
        return target in {_digits_only(n) for n in _NUMBER.findall(self.text)}

    def attribute(self, value: str) -> str | None:
        """Which stored field a value came from, if any."""
        lowered = value.strip().lower()
        for name, stored in self.fields.items():
            if stored and lowered in str(stored).lower():
                return name
        return None


@dataclass(frozen=True)
class GroundingVerdict:
    grounded: bool
    reason: str
    unsupported: tuple[str, ...] = ()

    @property
    def as_dict(self) -> dict[str, Any]:
        return {
            "grounded": self.grounded,
            "reason": self.reason,
            "unsupported": list(self.unsupported),
        }


GROUNDED = GroundingVerdict(True, "ok")


def check_claim(value: str, evidence: Evidence, *, token: str = "") -> GroundingVerdict:
    """Decide whether a filled token may be used.

    Returns a verdict rather than raising: the caller drops the sentence and
    carries on, and the whole report is persisted on the message.
    """
    if not value or not value.strip():
        return GroundingVerdict(False, "empty value")

    unsupported: list[str] = []

    for number in _NUMBER.findall(value):
        if not evidence.contains_number(number):
            unsupported.append(number)

    for match in _PROPER_NOUN.finditer(value):
        phrase = match.group(0)
        if phrase.lower() in _COMMON_CAPITALS:
            continue
        # A multi-word phrase is accepted if the evidence contains the whole
        # phrase or every word of it; company names get written many ways.
        words = [w for w in phrase.split() if w.lower() not in _COMMON_CAPITALS]
        if not words:
            continue
        if evidence.contains(phrase) or all(evidence.contains(w) for w in words):
            continue
        unsupported.append(phrase)

    if unsupported:
        verdict = GroundingVerdict(
            False,
            "contains specifics absent from the stored evidence",
            tuple(dict.fromkeys(unsupported)),
        )
        logger.warning(
            "grounding check blocked token %r: unsupported %s", token, verdict.unsupported
        )
        return verdict

    return GROUNDED


def build_evidence(lead: Any, company: Any) -> Evidence:
    """Assemble the evidence set for a lead from stored columns only."""
    signal = (getattr(lead, "raw_data", None) or {}).get("observed_signal") or {}

    fields: dict[str, str] = {
        "lead.first_name": getattr(lead, "first_name", "") or "",
        "lead.last_name": getattr(lead, "last_name", "") or "",
        "lead.job_title": getattr(lead, "job_title", "") or "",
        "company.name": getattr(company, "name", "") or "",
        "company.industry": getattr(company, "industry", "") or "",
        "company.region": getattr(company, "region", "") or "",
        "company.country": getattr(company, "country", "") or "",
        "company.description": getattr(company, "description", "") or "",
    }
    if getattr(company, "employee_count", None) is not None:
        fields["company.employee_count"] = str(company.employee_count)
    if signal.get("text"):
        fields["lead.observed_signal"] = signal["text"]

    urls = [
        url
        for url in (
            getattr(lead, "source_url", None),
            getattr(company, "source_url", None),
            signal.get("source_url"),
        )
        if url
    ]

    return Evidence(
        fields={k: v for k, v in fields.items() if v},
        source_urls=list(dict.fromkeys(urls)),
    )
