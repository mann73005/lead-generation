"""Reply classification and response drafting.

Two things happen here and they are deliberately separate:

  classify_reply   decides intent from a fixed label set, with a confidence.
  draft_response   writes a reply for a human to approve.

Nothing sends. The drafted text is persisted unsent and requires an explicit
approval action, which is the human-in-the-loop step the brief asks for.

A deterministic keyword pass runs first and is used when the model is
unavailable or unsure. It is not a fallback bolted on afterwards: an outreach
system that silently stops classifying when a quota runs out is worse than one
that classifies a little less well.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from app.core.logging import get_logger
from app.models.enums import ReplyIntent

logger = get_logger(__name__)

INTENTS = tuple(i.value for i in ReplyIntent)

CLASSIFY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": list(INTENTS)},
        "confidence": {"type": "number", "description": "0.0 to 1.0"},
        "reasoning": {"type": "string", "description": "One sentence."},
        "draft_response": {
            "type": "string",
            "description": "A short reply for a human to review and send.",
        },
    },
    "required": ["intent", "confidence", "reasoning", "draft_response"],
}

CLASSIFY_PROMPT = """\
Classify the intent of this reply to a cold sales email, and draft a response \
for a human to approve.

Our product: {product_name} — {product_description}
Recipient: {lead_name}, {job_title} at {company_name}

Their reply:
---
{reply_text}
---

Intents:
- interested: wants to talk, meet, or move forward.
- needs_info: open but wants more detail, pricing, a deck or a demo first.
- not_now: not refusing outright, but timing is wrong.
- wrong_person: not their remit; points elsewhere or says they are not involved.
- unsubscribe: wants no further contact.

Draft a reply of two to four sentences in the same register as theirs. If they \
named a colleague, acknowledge it and ask for an introduction. If they asked \
for something specific, say you will send it. Never invent a price, a metric, \
a customer name or a date. Sign off as {sender_name}.
"""

#: Scored before the model runs. Phrases are weighted so an explicit opt-out
#: beats a polite preamble — "thanks, but please remove me" is an unsubscribe,
#: not interest.
KEYWORD_RULES: dict[str, list[tuple[str, int]]] = {
    ReplyIntent.UNSUBSCRIBE: [
        ("unsubscribe", 5), ("remove me", 5), ("take me off", 5), ("opt out", 5),
        ("stop emailing", 5), ("do not contact", 5), ("don't contact", 5),
        ("not interested", 3), ("no thanks", 2),
    ],
    ReplyIntent.WRONG_PERSON: [
        ("wrong person", 5), ("not my", 4), ("reach out to", 3), ("speak to", 3),
        ("contact our", 4), ("my colleague", 4), ("i no longer", 4),
        ("left the company", 5), ("handles this", 3), ("better placed", 3),
        ("forward this", 3), ("responsible for", 2),
    ],
    ReplyIntent.NOT_NOW: [
        ("next quarter", 5), ("next year", 4), ("circle back", 4), ("revisit", 3),
        ("not right now", 5), ("bad timing", 4), ("busy", 2), ("later", 2),
        ("budget", 2), ("already have", 3), ("in a few months", 4),
    ],
    ReplyIntent.NEEDS_INFO: [
        ("more information", 5), ("more info", 5), ("send me", 4), ("details", 3),
        ("pricing", 4), ("how does", 3), ("case study", 4), ("deck", 3),
        ("what does", 3), ("tell me more", 5), ("learn more", 4),
    ],
    ReplyIntent.INTERESTED: [
        ("let's talk", 5), ("lets talk", 5), ("book a", 4), ("schedule", 4),
        ("set up a call", 5), ("happy to chat", 5), ("sounds good", 3),
        ("works for me", 4), ("calendar", 3), ("keen", 3), ("interested", 3),
        ("tuesday", 2), ("wednesday", 2), ("next week", 2),
    ],
}


@dataclass
class Classification:
    intent: str
    confidence: float
    reasoning: str
    draft_response: str | None
    model: str

    @property
    def as_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "model": self.model,
        }


def classify_by_keywords(text: str) -> tuple[str, float, str]:
    """Deterministic pass. Returns (intent, confidence, reasoning)."""
    lowered = f" {re.sub(r'\\s+', ' ', text.lower())} "
    scores: dict[str, int] = {}
    hits: dict[str, list[str]] = {}

    for intent, rules in KEYWORD_RULES.items():
        for phrase, weight in rules:
            if phrase in lowered:
                scores[intent] = scores.get(intent, 0) + weight
                hits.setdefault(intent, []).append(phrase)

    if not scores:
        # No signal at all. The least committal label is the honest answer:
        # a reply we cannot read is not evidence of interest.
        return ReplyIntent.NEEDS_INFO, 0.2, "no recognised phrases; defaulted"

    best = max(scores, key=lambda k: scores[k])
    total = sum(scores.values())
    confidence = min(0.85, 0.4 + 0.5 * (scores[best] / total))
    return best, round(confidence, 2), f"matched {', '.join(hits[best][:3])}"


def classify_reply(
    text: str,
    *,
    lead: Any = None,
    company: Any = None,
    product: Any = None,
    sender_name: str = "",
    llm: Any = None,
) -> Classification:
    """Classify a reply and draft an answer."""
    keyword_intent, keyword_confidence, keyword_reason = classify_by_keywords(text)

    if llm is None:
        return Classification(
            intent=keyword_intent,
            confidence=keyword_confidence,
            reasoning=f"keyword classifier: {keyword_reason}",
            draft_response=None,
            model="keyword",
        )

    from app.providers import Message

    prompt = CLASSIFY_PROMPT.format(
        product_name=getattr(product, "name", "our product"),
        product_description=getattr(product, "description", ""),
        lead_name=getattr(lead, "full_name", "there") if lead else "there",
        job_title=getattr(lead, "job_title", "") if lead else "",
        company_name=getattr(company, "name", "") if company else "",
        reply_text=text.strip()[:4000],
        sender_name=sender_name or "the team",
    )

    try:
        response = llm.generate(
            [Message(role="user", text=prompt)], json_schema=CLASSIFY_SCHEMA, temperature=0.1
        )
        parsed = json.loads(response.text)
        intent = str(parsed.get("intent", "")).strip()

        if intent not in INTENTS:
            # The label set is fixed; an answer outside it is not usable, so
            # the deterministic result stands rather than inventing a category.
            logger.warning("model returned an unknown intent %r; using keywords", intent)
            return Classification(
                keyword_intent, keyword_confidence,
                f"model returned invalid intent {intent!r}; keyword classifier: {keyword_reason}",
                None, "keyword",
            )

        return Classification(
            intent=intent,
            confidence=float(parsed.get("confidence", 0.5)),
            reasoning=str(parsed.get("reasoning", ""))[:500],
            draft_response=str(parsed.get("draft_response", "")).strip() or None,
            model=response.model,
        )
    except Exception as exc:
        logger.warning("reply classification fell back to keywords: %s", exc)
        return Classification(
            keyword_intent, keyword_confidence,
            f"model unavailable ({type(exc).__name__}); keyword classifier: {keyword_reason}",
            None, "keyword",
        )
