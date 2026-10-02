"""Fills the Appendix A skeleton from stored data.

Division of labour, which is the point of the design:

  resolve_tokens   works out a value and a provenance for every token. Most
                   come straight from a database column, so they are grounded
                   by construction. Two are phrased by the model.
  check_claim      (app.ai.grounding) decides whether a model-phrased value is
                   allowed to be used.
  render           assembles the email, dropping any sentence whose required
                   token did not survive, and omitting optional tokens cleanly.

The skeleton itself is never edited: the sentences, their order and their
locked copy come from the product profile, and this module only substitutes
tokens or removes whole sentences.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.ai.grounding import GROUNDED, Evidence, GroundingVerdict, build_evidence, check_claim
from app.core.logging import get_logger
from app.core.policy import OutreachTemplate, ProductConfig

logger = get_logger(__name__)

_TOKEN = re.compile(r"\{\{(\w+)\}\}")

#: Tokens the model is allowed to phrase. Everything else is copied from a
#: column or chosen from the configured mapping, which is why the grounding
#: check only has to police two values rather than the whole email.
MODEL_TOKENS = (
    "observed_signal_sentence",
    "observed_signal_short",
    "one_line_relevance_hypothesis",
)

PHRASING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "observed_signal_sentence": {
            "type": "string",
            "description": (
                "Rephrase the given fact as a natural clause that completes "
                "'I noticed ...'. Add nothing to it."
            ),
        },
        "observed_signal_short": {
            "type": "string",
            "description": (
                "The same fact as a noun phrase of at most five words, for a "
                "subject line. No company name, no verb, no punctuation."
            ),
        },
        "one_line_relevance_hypothesis": {
            "type": "string",
            "description": (
                "One clause saying why the capability might matter to them, "
                "phrased as a hypothesis. State no new facts."
            ),
        },
    },
    "required": [
        "observed_signal_sentence",
        "observed_signal_short",
        "one_line_relevance_hypothesis",
    ],
}

#: The subject already carries the company name, and a subject that runs past
#: this is truncated by every mail client anyway.
SHORT_SIGNAL_MAX_WORDS = 6

PHRASING_PROMPT = """\
You are writing two fragments of a cold outreach email. You may only rephrase \
the facts below. Do not add a company name, a number, a date, a metric or any \
detail that is not already stated here — anything you invent will be detected \
and the sentence discarded.

Facts on file:
{facts}

Capability being offered: {capability}

Write:
1. `observed_signal_sentence` — completes "I noticed ...". Lower case start, \
no trailing full stop.
2. `observed_signal_short` — the same fact as a noun phrase of at most five \
words, for a subject line. Do not repeat the company name; it already appears \
in the subject. Example shape: "the new supply chain lead".
3. `one_line_relevance_hypothesis` — completes the sentence "Given <company>'s \
<context>, ...". Phrase it as a hypothesis ("it may be worth...", "there may \
be room to..."). Lower case start, no trailing full stop. Say why the \
capability might matter to this person in particular — do not restate the \
capability itself, it already appears in the previous sentence.
"""


@dataclass
class ResolvedToken:
    name: str
    value: str | None
    origin: str
    source_field: str | None = None
    source_url: str | None = None
    verdict: GroundingVerdict = GROUNDED

    @property
    def usable(self) -> bool:
        return bool(self.value) and self.verdict.grounded

    @property
    def as_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "origin": self.origin,
            "source_field": self.source_field,
            "source_url": self.source_url,
            "verdict": self.verdict.as_dict,
        }


@dataclass
class RenderedEmail:
    subject: str
    body_text: str
    tokens: dict[str, Any] = field(default_factory=dict)
    dropped_sentences: list[str] = field(default_factory=list)
    grounding_report: dict[str, Any] = field(default_factory=dict)


def _condense(text: str, *, company_name: str) -> str:
    """Deterministic fallback for the subject-line fragment.

    Used when the model is unavailable or returns something too long. Strips
    the company name — the subject already opens with it — and keeps the tail
    of the first clause, which is where the actual news usually sits.
    """
    head = re.split(r"(?<=[.!?])\s", text.strip())[0].rstrip(".")
    without_company = re.sub(re.escape(company_name), "", head, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"^(has|have|is|are|was|were|will|recently)\b\s*", "", without_company, flags=re.I)
    words = cleaned.split()
    return " ".join(words[:SHORT_SIGNAL_MAX_WORDS]) if words else head[:60]


def _match_pain_point(
    profile: ProductConfig, evidence: Evidence, job_title: str
) -> tuple[str, Any] | None:
    """Pick the pain point this lead most likely owns.

    Two axes. Evidence about the company is the stronger signal and is weighted
    accordingly; the lead's own job title is the weaker one but applies far
    more often, since a Head of Supply Chain owns allocation whether or not any
    article mentions a stockout. Falls back to the configured default, which is
    a positioning choice rather than a claim about the company.
    """
    haystack = evidence.text.lower()
    title = job_title.lower()
    best: tuple[int, str, Any] | None = None

    for key, pain in profile.pain_points.items():
        score = 2 * sum(1 for s in pain.signals if s.lower() in haystack)
        score += sum(1 for s in pain.title_signals if s.lower() in title)
        if score and (best is None or score > best[0]):
            best = (score, key, pain)

    if best:
        return best[1], best[2]
    if profile.default:
        return profile.default, profile.pain_points[profile.default]
    return None


def resolve_tokens(
    lead: Any,
    company: Any,
    profile: ProductConfig,
    *,
    sender_name: str,
    llm: Any | None = None,
    proposed_time_window: str | None = None,
) -> dict[str, ResolvedToken]:
    """Work out a value and a provenance for every token in the skeleton."""
    evidence = build_evidence(lead, company)
    signal = (getattr(lead, "raw_data", None) or {}).get("observed_signal") or {}
    tokens: dict[str, ResolvedToken] = {}

    def put(name: str, value: str | None, origin: str, **extra: Any) -> None:
        tokens[name] = ResolvedToken(name=name, value=value, origin=origin, **extra)

    # --- straight from stored columns ---------------------------------------
    put("first_name", lead.first_name, "field", source_field="lead.first_name",
        source_url=lead.source_url)
    put("company_name", company.name, "field", source_field="company.name",
        source_url=company.source_url)
    put("sender_name", sender_name, "config")
    put("product_name", profile.identity.name, "config")

    # --- chosen from the configured mappings --------------------------------
    segment = profile.identity.segment_for(
        " ".join(filter(None, [company.description, company.industry]))
    )
    put("company_segment", segment, "derived", source_field="company.industry")

    matched = _match_pain_point(profile, evidence, lead.job_title or "")
    if matched:
        key, pain = matched
        put("pain_point_category", pain.label, "derived", source_field=f"pain_points.{key}")
        put("value_prop_for_pain_point", pain.capability, "config",
            source_field=f"pain_points.{key}.capability")
    else:
        # No evidence pointed at a specific pain, so nothing is asserted about
        # one. The sentence that needs it will be dropped.
        put("pain_point_category", None, "derived")
        put("value_prop_for_pain_point", None, "derived")

    # A concrete, checkable description assembled from columns — never prose.
    context_parts = [
        f"{company.employee_count}-person" if company.employee_count else None,
        company.industry,
        f"business in {company.region}" if company.region else None,
    ]
    context = " ".join(p for p in context_parts if p).strip()
    put("specific_context_detail", context or None, "derived",
        source_field="company.industry/region/employee_count",
        source_url=company.source_url)

    # --- optional: filled only when a stored value exists --------------------
    put("proposed_time_window", proposed_time_window, "config")
    # No quantified customer outcomes or proof points are stored, so these are
    # omitted rather than invented. That is the behaviour Appendix A asks for.
    put("quantified_outcome_optional", None, "unavailable")
    put("optional_soft_proof_point", None, "unavailable")

    # --- model-phrased, then checked ----------------------------------------
    raw_signal = signal.get("text")
    signal_url = signal.get("source_url") or lead.source_url

    phrasing: dict[str, str] = {}
    if raw_signal and llm is not None:
        phrasing = _phrase_with_model(llm, evidence, profile, matched)

    sentence = phrasing.get("observed_signal_sentence") or (
        # Deterministic fallback: the stored fact verbatim. Less fluent, but it
        # cannot be wrong, and it keeps the feature working when the LLM is out
        # of quota.
        raw_signal[0].lower() + raw_signal[1:].rstrip(".") if raw_signal else None
    )
    if sentence:
        verdict = check_claim(sentence, evidence, token="observed_signal_sentence")
        put("observed_signal_sentence", sentence, "model" if phrasing else "field",
            source_field="lead.observed_signal", source_url=signal_url, verdict=verdict)

        short = phrasing.get("observed_signal_short")
        if short and len(short.split()) > SHORT_SIGNAL_MAX_WORDS:
            short = None  # too long for a subject line; fall back below
        if not short:
            short = _condense(raw_signal or sentence, company_name=company.name)
        # The subject renders as "<Company>'s <short>", so a leading article
        # produces "Acme's the new head of retail".
        short = re.sub(r"^(the|a|an)\s+", "", short, flags=re.IGNORECASE)
        put("observed_signal_short", short, "model" if phrasing.get("observed_signal_short") else "derived",
            source_field="lead.observed_signal", source_url=signal_url,
            verdict=check_claim(short, evidence, token="observed_signal_short"))
    else:
        put("observed_signal_sentence", None, "unavailable")
        put("observed_signal_short", None, "unavailable")

    hypothesis = phrasing.get("one_line_relevance_hypothesis")
    if hypothesis:
        put("one_line_relevance_hypothesis", hypothesis, "model", source_url=signal_url,
            verdict=check_claim(hypothesis, evidence, token="one_line_relevance_hypothesis"))
    elif matched:
        # Fallback phrased purely from the configured capability, so it asserts
        # nothing about the company beyond what matched.
        put("one_line_relevance_hypothesis",
            f"it may be worth seeing whether we could help you {matched[1].capability}",
            "derived", source_field=f"pain_points.{matched[0]}.capability")
    else:
        put("one_line_relevance_hypothesis", None, "unavailable")

    return tokens


def _phrase_with_model(
    llm: Any, evidence: Evidence, profile: ProductConfig, matched: tuple[str, Any] | None
) -> dict[str, str]:
    """Ask the model to phrase two fragments. Failure is not fatal."""
    from app.providers import Message

    facts = "\n".join(f"- {name}: {value}" for name, value in evidence.fields.items())
    capability = matched[1].capability if matched else profile.identity.description

    try:
        response = llm.generate(
            [Message(role="user", text=PHRASING_PROMPT.format(facts=facts, capability=capability))],
            json_schema=PHRASING_SCHEMA,
            temperature=0.3,
        )
        import json

        parsed = json.loads(response.text)
        return {k: str(v).strip() for k, v in parsed.items() if v}
    except Exception as exc:
        # Falls back to the deterministic phrasing above. An email that reads a
        # little flatly beats no email at all.
        logger.warning("model phrasing unavailable, using stored text: %s", exc)
        return {}


def render(template: OutreachTemplate, tokens: dict[str, ResolvedToken]) -> RenderedEmail:
    """Assemble the email, dropping what cannot be grounded."""
    optional = template.optional_tokens

    def substitute(text: str) -> str:
        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            resolved = tokens.get(name)
            if resolved is None or not resolved.usable:
                return ""
            if name in optional:
                return f"{optional[name].prefix}{resolved.value}"
            return str(resolved.value)

        return _TOKEN.sub(replace, text)

    kept: list[str] = []
    dropped: list[str] = []

    for sentence in template.body:
        missing = [
            name
            for name in sentence.required
            if not (tokens.get(name) and tokens[name].usable)
        ]
        if missing:
            dropped.append(f"{sentence.id}: missing {', '.join(missing)}")
            continue

        names = _TOKEN.findall(sentence.text)
        # An optional sentence exists only to carry its tokens. With none of
        # them grounded the line is pure scaffolding — "P.S." on its own — and
        # its literal text would survive the emptiness check below, so it is
        # dropped here instead.
        if sentence.optional and names and not any(
            tokens.get(name) and tokens[name].usable for name in names
        ):
            dropped.append(f"{sentence.id}: optional, no grounded content")
            continue

        rendered = substitute(sentence.text).strip()
        # A sentence that collapsed to punctuation once its optional tokens
        # were removed is dropped rather than shipped as " - ."
        if not re.search(r"[A-Za-z0-9]", rendered):
            dropped.append(f"{sentence.id}: empty after token removal")
            continue
        kept.append(rendered)

    # First subject option whose tokens all resolved.
    subject = ""
    for option in template.subject_options:
        names = _TOKEN.findall(option)
        if all(tokens.get(n) and tokens[n].usable for n in names):
            subject = substitute(option).strip()
            break

    violations = {
        name: resolved.verdict.as_dict
        for name, resolved in tokens.items()
        if resolved.value and not resolved.verdict.grounded
    }

    return RenderedEmail(
        subject=subject,
        body_text="\n\n".join(kept),
        tokens={name: resolved.as_dict for name, resolved in tokens.items()},
        dropped_sentences=dropped,
        grounding_report={
            "checked": len(tokens),
            "blocked": len(violations),
            "violations": violations,
            "evidence_fields": sorted(
                {r.source_field for r in tokens.values() if r.source_field}
            ),
        },
    )
