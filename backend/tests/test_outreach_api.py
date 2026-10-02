"""End-to-end outreach: draft, send, open tracking, unsubscribe, suppression.

Sends go through the mock provider, so the suite never touches a real gateway
and never emails anybody.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Campaign,
    CampaignLead,
    EmailEvent,
    EmailMessage,
    Lead,
    SuppressedEmail,
)
from app.models.enums import EmailEventType, MessageStatus, SuppressionReason
from app.providers.mocks import MockEmailProvider
from app.services.product_profile import ensure_product_profile
from app.services.suppression import suppress

API = "/api/v1"


@pytest.fixture
def email_provider(monkeypatch) -> MockEmailProvider:
    provider = MockEmailProvider()
    monkeypatch.setattr("app.services.outreach.get_email_provider", lambda: provider)
    return provider


@pytest.fixture(autouse=True)
def profile(db: Session):
    return ensure_product_profile(db)


@pytest.fixture
def signalled_lead(db: Session, lead: Lead) -> Lead:
    """A lead carrying a grounded observed signal, as discovery would leave it."""
    lead.raw_data = {
        "observed_signal": {
            "text": "Example Fashion has appointed Rahul Sharma to lead merchandising.",
            "source_url": "https://examplefashion.com/team",
        }
    }
    db.flush()
    return lead


@pytest.fixture
def campaign_lead(db: Session, signalled_lead: Lead) -> CampaignLead:
    campaign = Campaign(
        name="Test Campaign",
        sender_name="Test Sender",
        sender_email="sender@examplefashion.com",
    )
    db.add(campaign)
    db.flush()
    link = CampaignLead(campaign_id=campaign.id, lead_id=signalled_lead.id)
    db.add(link)
    db.flush()
    return link


def draft(client: TestClient, auth: dict[str, str], cl: CampaignLead):
    return client.post(
        f"{API}/campaigns/{cl.campaign_id}/leads/{cl.lead_id}/messages", headers=auth
    )


# --------------------------------------------------------------------------
# Generating a draft
# --------------------------------------------------------------------------


def test_draft_is_generated_from_stored_data(
    client: TestClient, auth: dict[str, str], campaign_lead: CampaignLead
) -> None:
    response = draft(client, auth, campaign_lead)
    assert response.status_code == 201, response.text

    body = response.json()
    assert body["subject"]
    assert "Hi Rahul," in body["body_text"]
    assert body["status"] == MessageStatus.DRAFT
    # Nothing is sent by generating.
    assert body["sent_at"] is None


def test_draft_reports_token_provenance_and_grounding(
    client: TestClient, auth: dict[str, str], campaign_lead: CampaignLead
) -> None:
    """A reviewer has to be able to ask "where did this sentence come from?"."""
    body = draft(client, auth, campaign_lead).json()

    assert body["grounding_report"]["checked"] > 0
    assert body["grounding_report"]["blocked"] == 0
    first_name = body["tokens"]["first_name"]
    assert first_name["source_field"] == "lead.first_name"
    assert first_name["verdict"]["grounded"] is True


def test_unavailable_optional_tokens_are_omitted_not_invented(
    client: TestClient, auth: dict[str, str], campaign_lead: CampaignLead
) -> None:
    body = draft(client, auth, campaign_lead).json()
    assert "P.S." not in body["body_text"]
    assert any("ps" in dropped for dropped in body["dropped_sentences"])


def test_draft_for_a_lead_outside_the_campaign_404s(
    client: TestClient, auth: dict[str, str], campaign_lead: CampaignLead, company
) -> None:
    other = client.post(
        f"{API}/leads",
        headers=auth,
        json={
            "company_id": str(company.id),
            "first_name": "Outsider",
            "job_title": "Head of Merchandising",
            "source_url": "https://examplefashion.com/team",
        },
    ).json()
    response = client.post(
        f"{API}/campaigns/{campaign_lead.campaign_id}/leads/{other['id']}/messages",
        headers=auth,
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------
# Sending
# --------------------------------------------------------------------------


def test_sending_records_events_and_moves_the_score(
    client: TestClient,
    auth: dict[str, str],
    campaign_lead: CampaignLead,
    email_provider: MockEmailProvider,
) -> None:
    before = client.get(f"{API}/leads/{campaign_lead.lead_id}", headers=auth).json()
    message = draft(client, auth, campaign_lead).json()

    response = client.post(f"{API}/messages/{message['id']}/send", headers=auth)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == MessageStatus.SENT
    assert len(email_provider.sent) == 1

    after = client.get(f"{API}/leads/{campaign_lead.lead_id}", headers=auth).json()
    kinds = {event["event_type"] for event in after["events"]}
    assert {EmailEventType.SENT, EmailEventType.DELIVERED} <= kinds
    assert after["score"]["total_score"] > before["score"]["total_score"]


def test_the_sent_email_carries_a_pixel_and_an_unsubscribe_link(
    client: TestClient,
    auth: dict[str, str],
    campaign_lead: CampaignLead,
    email_provider: MockEmailProvider,
) -> None:
    message = draft(client, auth, campaign_lead).json()
    client.post(f"{API}/messages/{message['id']}/send", headers=auth)

    html = email_provider.sent[0]["html"]
    assert "/t/" in html and ".png" in html
    assert "/u/" in html
    # One-click opt-out for clients that honour the header.
    assert "List-Unsubscribe" in email_provider.sent[0]["headers"]


def test_a_message_cannot_be_sent_twice(
    client: TestClient,
    auth: dict[str, str],
    campaign_lead: CampaignLead,
    email_provider: MockEmailProvider,
) -> None:
    message = draft(client, auth, campaign_lead).json()
    assert client.post(f"{API}/messages/{message['id']}/send", headers=auth).status_code == 200

    second = client.post(f"{API}/messages/{message['id']}/send", headers=auth)
    assert second.status_code == 409
    assert len(email_provider.sent) == 1


def test_send_to_a_suppressed_lead_is_refused(
    client: TestClient,
    auth: dict[str, str],
    db: Session,
    campaign_lead: CampaignLead,
    email_provider: MockEmailProvider,
) -> None:
    """The suppression check lives inside the send path, so there is no way
    for a caller to reach the provider around it."""
    suppress(db, campaign_lead.lead.email, reason=SuppressionReason.UNSUBSCRIBED)
    message = draft(client, auth, campaign_lead).json()

    response = client.post(f"{API}/messages/{message['id']}/send", headers=auth)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "recipient_suppressed"
    assert email_provider.sent == []

    stored = db.get(EmailMessage, message["id"])
    assert stored.status == MessageStatus.SUPPRESSED


# --------------------------------------------------------------------------
# Open tracking
# --------------------------------------------------------------------------


def test_the_pixel_records_an_open_and_raises_the_score(
    client: TestClient,
    auth: dict[str, str],
    db: Session,
    campaign_lead: CampaignLead,
    email_provider: MockEmailProvider,
) -> None:
    message = draft(client, auth, campaign_lead).json()
    client.post(f"{API}/messages/{message['id']}/send", headers=auth)
    before = client.get(f"{API}/leads/{campaign_lead.lead_id}", headers=auth).json()

    token = db.get(EmailMessage, message["id"]).tracking_token
    response = client.get(f"/t/{token}.png")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert "no-store" in response.headers["cache-control"]

    after = client.get(f"{API}/leads/{campaign_lead.lead_id}", headers=auth).json()
    assert after["score"]["status"] == "opened"
    assert after["score"]["total_score"] > before["score"]["total_score"]
    assert any("Email opened" == h["reason"] for h in after["score_history"])


def test_the_pixel_needs_no_authentication(
    client: TestClient, auth: dict[str, str], db: Session, campaign_lead: CampaignLead,
    email_provider: MockEmailProvider,
) -> None:
    """It is fetched by a mail client, which has no token to present."""
    message = draft(client, auth, campaign_lead).json()
    client.post(f"{API}/messages/{message['id']}/send", headers=auth)
    token = db.get(EmailMessage, message["id"]).tracking_token
    assert client.get(f"/t/{token}.png").status_code == 200


def test_an_unknown_pixel_token_still_returns_an_image(client: TestClient) -> None:
    """A 404 would leave a broken image in a prospect's inbox, and would tell a
    scanner which tokens exist."""
    response = client.get("/t/not-a-real-token.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"


def test_rapid_repeat_requests_count_as_one_open(
    client: TestClient, auth: dict[str, str], db: Session, campaign_lead: CampaignLead,
    email_provider: MockEmailProvider,
) -> None:
    """Gmail's image proxy may fetch the same pixel several times at once."""
    message = draft(client, auth, campaign_lead).json()
    client.post(f"{API}/messages/{message['id']}/send", headers=auth)
    token = db.get(EmailMessage, message["id"]).tracking_token

    for _ in range(4):
        client.get(f"/t/{token}.png")

    opens = db.scalars(
        select(EmailEvent).where(
            EmailEvent.message_id == message["id"],
            EmailEvent.event_type == EmailEventType.OPENED,
        )
    ).all()
    assert len(opens) == 1


# --------------------------------------------------------------------------
# Unsubscribe — the brief calls this non-negotiable
# --------------------------------------------------------------------------


def test_unsubscribe_suppresses_the_address_and_zeroes_the_score(
    client: TestClient, auth: dict[str, str], db: Session, campaign_lead: CampaignLead,
    email_provider: MockEmailProvider,
) -> None:
    message = draft(client, auth, campaign_lead).json()
    client.post(f"{API}/messages/{message['id']}/send", headers=auth)

    response = client.get(f"/u/{campaign_lead.unsubscribe_token}")
    assert response.status_code == 200
    assert "unsubscribed" in response.text.lower()

    assert db.scalar(
        select(SuppressedEmail).where(SuppressedEmail.email == campaign_lead.lead.email)
    )
    after = client.get(f"{API}/leads/{campaign_lead.lead_id}", headers=auth).json()
    assert after["score"]["status"] == "unsubscribed"
    assert after["score"]["total_score"] == 0


def test_unsubscribe_blocks_every_later_send(
    client: TestClient, auth: dict[str, str], campaign_lead: CampaignLead,
    email_provider: MockEmailProvider,
) -> None:
    first = draft(client, auth, campaign_lead).json()
    client.post(f"{API}/messages/{first['id']}/send", headers=auth)
    client.get(f"/u/{campaign_lead.unsubscribe_token}")

    second = draft(client, auth, campaign_lead).json()
    response = client.post(f"{API}/messages/{second['id']}/send", headers=auth)
    assert response.status_code == 409
    assert len(email_provider.sent) == 1


def test_unsubscribing_twice_is_not_an_error(
    client: TestClient, auth: dict[str, str], campaign_lead: CampaignLead,
    email_provider: MockEmailProvider,
) -> None:
    message = draft(client, auth, campaign_lead).json()
    client.post(f"{API}/messages/{message['id']}/send", headers=auth)
    assert client.get(f"/u/{campaign_lead.unsubscribe_token}").status_code == 200
    assert client.get(f"/u/{campaign_lead.unsubscribe_token}").status_code == 200


def test_an_unknown_unsubscribe_token_is_rejected(client: TestClient) -> None:
    assert client.get("/u/not-a-real-token").status_code == 404


# --------------------------------------------------------------------------
# Product profile — editable at runtime, which is what the console needs
# --------------------------------------------------------------------------


def test_the_product_profile_is_readable_and_editable(
    client: TestClient, auth: dict[str, str]
) -> None:
    current = client.get(f"{API}/product-profile", headers=auth)
    assert current.status_code == 200
    assert current.json()["name"]

    updated = client.patch(
        f"{API}/product-profile", headers=auth, json={"sender_name": "A New Sender"}
    )
    assert updated.status_code == 200
    assert updated.json()["sender_name"] == "A New Sender"


def test_an_inconsistent_template_is_rejected(
    client: TestClient, auth: dict[str, str]
) -> None:
    """A sentence requiring a token it does not contain would be undroppable.
    That has to fail here, not when a salesperson tries to mail someone."""
    broken = {
        "subject_options": ["Hello {{first_name}}"],
        "body": [{"id": "greeting", "text": "Hi there,", "required": ["first_name"]}],
        "optional_tokens": {},
    }
    response = client.patch(f"{API}/product-profile", headers=auth, json={"template": broken})
    assert response.status_code == 422
