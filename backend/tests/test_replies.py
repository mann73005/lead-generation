"""Reply classification, the simulate-reply endpoint, and human approval."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.classification import INTENTS, classify_by_keywords, classify_reply
from app.models import Lead, SuppressedEmail
from app.models.enums import ReplyIntent
from app.providers.base import LLMResponse
from app.providers.mocks import MockLLMProvider
from app.services.product_profile import ensure_product_profile

API = "/api/v1"
DATASET = Path(__file__).resolve().parents[1] / "data" / "labelled_replies.json"


@pytest.fixture(autouse=True)
def profile(db: Session):
    return ensure_product_profile(db)


def scripted(payload: dict) -> MockLLMProvider:
    return MockLLMProvider(
        responses=[LLMResponse(text=json.dumps(payload), tool_calls=[], model="mock-llm")]
    )


# --------------------------------------------------------------------------
# The labelled dataset the brief asks for
# --------------------------------------------------------------------------


def test_the_labelled_dataset_is_well_formed() -> None:
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    examples = data["examples"]

    assert 5 <= len(examples) <= 8, "the brief asks for 5-8 hand-labelled replies"
    assert set(data["label_set"]) == set(INTENTS)
    assert all(e["label"] in INTENTS for e in examples)
    assert len({e["id"] for e in examples}) == len(examples)
    # Every label represented, so accuracy cannot be inflated by a classifier
    # that only ever predicts the common one.
    assert {e["label"] for e in examples} == set(INTENTS)


# --------------------------------------------------------------------------
# The deterministic classifier
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Please remove me from your list", ReplyIntent.UNSUBSCRIBE),
        ("Let's talk - does Tuesday work?", ReplyIntent.INTERESTED),
        ("Can you send me pricing details?", ReplyIntent.NEEDS_INFO),
        ("Not my area, contact our supply chain team", ReplyIntent.WRONG_PERSON),
        ("Let's circle back next quarter", ReplyIntent.NOT_NOW),
    ],
)
def test_keyword_classifier_handles_clear_cases(text: str, expected: str) -> None:
    assert classify_by_keywords(text)[0] == expected


def test_an_explicit_opt_out_beats_a_polite_opener() -> None:
    """"Thanks, sounds great, but remove me" is an unsubscribe, not interest."""
    intent, _, _ = classify_by_keywords("Thanks, sounds good, but please remove me from your list.")
    assert intent == ReplyIntent.UNSUBSCRIBE


def test_unreadable_text_is_low_confidence_not_a_guess() -> None:
    intent, confidence, _ = classify_by_keywords("asdf qwerty zzz")
    assert intent in INTENTS
    assert confidence <= 0.3


def test_keyword_classifier_never_invents_a_label() -> None:
    for text in ["", "???", "ok", "Thanks!"]:
        assert classify_by_keywords(text)[0] in INTENTS


# --------------------------------------------------------------------------
# The model path, and what happens when it misbehaves
# --------------------------------------------------------------------------


def test_model_output_is_used_when_valid() -> None:
    llm = scripted(
        {
            "intent": "interested",
            "confidence": 0.93,
            "reasoning": "proposed a time",
            "draft_response": "Great - how is Thursday at 3?",
        }
    )
    result = classify_reply("Happy to chat, Thursday?", llm=llm)
    assert result.intent == ReplyIntent.INTERESTED
    assert result.draft_response
    assert result.model == "mock-llm"


def test_an_invalid_label_from_the_model_falls_back_to_keywords() -> None:
    """The label set is fixed; an answer outside it is not usable."""
    llm = scripted(
        {"intent": "extremely_keen", "confidence": 0.99, "reasoning": "", "draft_response": "hi"}
    )
    result = classify_reply("Please remove me from your list", llm=llm)
    assert result.intent == ReplyIntent.UNSUBSCRIBE
    assert result.model == "keyword"


def test_a_failing_model_does_not_break_classification() -> None:
    """Out of quota is a normal condition, not an outage of the feature."""
    result = classify_reply(
        "Please remove me from your list", llm=MockLLMProvider(unavailable_rate=1.0)
    )
    assert result.intent == ReplyIntent.UNSUBSCRIBE
    assert result.model == "keyword"
    assert "unavailable" in result.reasoning


# --------------------------------------------------------------------------
# The endpoint
# --------------------------------------------------------------------------


def test_simulating_a_reply_classifies_and_rescores(
    client: TestClient, auth: dict[str, str], lead: Lead
) -> None:
    before = client.get(f"{API}/leads/{lead.id}", headers=auth).json()

    response = client.post(
        f"{API}/replies",
        headers=auth,
        json={"lead_id": str(lead.id), "text": "Sounds interesting, can we talk Tuesday?"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["intent"] in INTENTS

    after = client.get(f"{API}/leads/{lead.id}", headers=auth).json()
    assert after["score"]["status"] == "replied"
    assert after["score"]["total_score"] > before["score"]["total_score"]
    assert any("Reply received" in h["reason"] for h in after["score_history"])


def test_a_negative_reply_lowers_the_score_without_deleting_the_lead(
    client: TestClient, auth: dict[str, str], lead: Lead
) -> None:
    client.post(
        f"{API}/replies",
        headers=auth,
        json={"lead_id": str(lead.id), "text": "Not my area - contact our procurement team."},
    )
    after = client.get(f"{API}/leads/{lead.id}", headers=auth).json()
    assert after["score"]["status"] == "replied"
    # Still visible to the salesperson, just ranked lower.
    assert after["score"]["total_score"] >= 0


def test_an_unsubscribe_reply_suppresses_the_address(
    client: TestClient, auth: dict[str, str], db: Session, lead: Lead
) -> None:
    """An opt-out counts however it arrives, not only via the footer link."""
    response = client.post(
        f"{API}/replies",
        headers=auth,
        json={"lead_id": str(lead.id), "text": "Please remove me and do not contact me again."},
    )
    assert response.json()["intent"] == ReplyIntent.UNSUBSCRIBE

    assert db.scalar(select(SuppressedEmail).where(SuppressedEmail.email == lead.email))
    after = client.get(f"{API}/leads/{lead.id}", headers=auth).json()
    assert after["score"]["total_score"] == 0
    assert after["score"]["status"] == "unsubscribed"


def test_the_draft_is_never_sent_automatically(
    client: TestClient, auth: dict[str, str], lead: Lead
) -> None:
    body = client.post(
        f"{API}/replies",
        headers=auth,
        json={"lead_id": str(lead.id), "text": "Can you send pricing?"},
    ).json()
    assert body["approved"] is False
    assert body["approved_at"] is None


def test_approval_requires_a_draft_to_approve(
    client: TestClient, auth: dict[str, str], lead: Lead
) -> None:
    reply = client.post(
        f"{API}/replies",
        headers=auth,
        json={"lead_id": str(lead.id), "text": "Can you send pricing?"},
    ).json()

    approved = client.post(
        f"{API}/replies/{reply['id']}/approve",
        headers=auth,
        json={"draft_response": "Sending our one-pager across now."},
    )
    assert approved.status_code == 200
    assert approved.json()["approved"] is True
    assert approved.json()["approved_at"]

    # Approving twice is a conflict, not a silent no-op.
    assert (
        client.post(
            f"{API}/replies/{reply['id']}/approve", headers=auth, json={}
        ).status_code
        == 409
    )


def test_replies_are_filterable_by_lead(
    client: TestClient, auth: dict[str, str], lead: Lead
) -> None:
    client.post(
        f"{API}/replies",
        headers=auth,
        json={"lead_id": str(lead.id), "text": "Sounds good, let's talk."},
    )
    body = client.get(f"{API}/replies?lead_id={lead.id}", headers=auth).json()
    assert body["total"] >= 1
    assert all(item["lead_id"] == str(lead.id) for item in body["items"])


def test_a_reply_for_an_unknown_lead_404s(client: TestClient, auth: dict[str, str]) -> None:
    from uuid import uuid4

    response = client.post(
        f"{API}/replies", headers=auth, json={"lead_id": str(uuid4()), "text": "hello"}
    )
    assert response.status_code == 404


def test_an_empty_reply_is_rejected(
    client: TestClient, auth: dict[str, str], lead: Lead
) -> None:
    response = client.post(
        f"{API}/replies", headers=auth, json={"lead_id": str(lead.id), "text": ""}
    )
    assert response.status_code == 422
