"""Generating and sending outreach.

`send_message` is the only route to the email provider in the whole codebase.
Everything that must happen on every send — the suppression check, the
recipient override, the event trail — lives here rather than in callers.
"""

from __future__ import annotations

from datetime import UTC, datetime
from html import escape

from sqlalchemy.orm import Session

from app.ai.email_builder import RenderedEmail, render, resolve_tokens
from app.core.config import settings
from app.core.exceptions import GroundingError, ProviderError, SuppressedRecipientError
from app.core.logging import get_logger
from app.models import CampaignLead, EmailMessage
from app.models.enums import EmailEventType, MessageStatus
from app.providers import get_email_provider, get_llm_provider
from app.services.events import record_event
from app.services.product_profile import get_active_profile, to_config
from app.services.suppression import is_suppressed

logger = get_logger(__name__)


def tracking_url(token: str) -> str:
    return f"{settings.public_base_url}/t/{token}.png"


def unsubscribe_url(token: str) -> str:
    return f"{settings.public_base_url}/u/{token}"


def _html_body(text: str, *, pixel: str, unsubscribe: str) -> str:
    """Wrap the plain text as HTML with the open pixel and the opt-out link.

    The pixel is last in the body so it loads after the content, and carries
    empty alt text so a client that blocks images shows nothing rather than a
    broken-image placeholder that advertises the tracking.
    """
    paragraphs = "\n".join(
        f"<p style=\"margin:0 0 16px;\">{escape(block).replace(chr(10), '<br>')}</p>"
        for block in text.split("\n\n")
        if block.strip()
    )
    return (
        '<!doctype html><html><body style="font-family:-apple-system,Segoe UI,'
        'Helvetica,Arial,sans-serif;font-size:15px;line-height:1.55;color:#1f2430;">'
        f"{paragraphs}"
        '<hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0 12px;">'
        f'<p style="font-size:12px;color:#6b7280;margin:0;">'
        f'Not relevant? <a href="{escape(unsubscribe)}" style="color:#6b7280;">'
        "Unsubscribe</a> and we will not contact you again.</p>"
        f'<img src="{escape(pixel)}" width="1" height="1" alt="" '
        'style="display:block;border:0;">'
        "</body></html>"
    )


def generate_message(db: Session, campaign_lead: CampaignLead) -> EmailMessage:
    """Build a grounded draft. Nothing is sent here."""
    lead = campaign_lead.lead
    profile_row = get_active_profile(db)
    profile = to_config(profile_row)

    rendered: RenderedEmail = render(
        profile.template,
        resolve_tokens(
            lead,
            lead.company,
            profile,
            sender_name=campaign_lead.campaign.sender_name or profile_row.sender_name,
            llm=get_llm_provider() if settings.llm_enabled else None,
        ),
    )

    if not rendered.subject or not rendered.body_text.strip():
        # Every token that could carry a specific claim failed its check, so
        # there is no honest email to send. Reported rather than padded out
        # with generic copy.
        raise GroundingError(
            "Not enough grounded data to compose an email for this lead",
            details={
                "dropped_sentences": rendered.dropped_sentences,
                "grounding_report": rendered.grounding_report,
            },
        )

    message = EmailMessage(
        campaign_lead_id=campaign_lead.id,
        subject=rendered.subject,
        body_text=rendered.body_text,
        body_html="",  # filled below, once the tracking token exists
        tokens=rendered.tokens,
        grounding_report=rendered.grounding_report,
        dropped_sentences=rendered.dropped_sentences,
        status=MessageStatus.DRAFT,
    )
    db.add(message)
    db.flush()

    message.body_html = _html_body(
        rendered.body_text,
        pixel=tracking_url(message.tracking_token),
        unsubscribe=unsubscribe_url(campaign_lead.unsubscribe_token),
    )
    db.flush()

    if rendered.dropped_sentences:
        logger.info(
            "message %s dropped %d sentence(s): %s",
            message.id,
            len(rendered.dropped_sentences),
            rendered.dropped_sentences,
        )
    return message


def send_message(db: Session, message: EmailMessage) -> EmailMessage:
    """Send a draft. The only path to the email provider."""
    campaign_lead = message.campaign_lead
    lead = campaign_lead.lead

    if message.status == MessageStatus.SENT:
        raise ProviderError("This message has already been sent")

    if is_suppressed(db, lead.email):
        message.status = MessageStatus.SUPPRESSED
        message.error = "Recipient is on the suppression list"
        db.flush()
        raise SuppressedRecipientError(
            "This lead has unsubscribed and cannot be contacted",
            details={"lead_id": str(lead.id)},
        )

    # Discovered prospects are never mailed. The lead's real address stays on
    # the record for the console, but delivery always goes to an inbox we
    # control unless the override is explicitly cleared.
    recipient = settings.email_override_to or lead.email
    if not recipient:
        raise ProviderError("No recipient address: the lead has no email and no override is set")

    if is_suppressed(db, recipient):
        message.status = MessageStatus.SUPPRESSED
        message.error = "Override recipient is on the suppression list"
        db.flush()
        raise SuppressedRecipientError("The configured recipient has unsubscribed")

    message.to_address = recipient
    profile = get_active_profile(db)

    try:
        sent = get_email_provider().send(
            to=recipient,
            subject=message.subject,
            html=message.body_html,
            text=message.body_text,
            from_name=campaign_lead.campaign.sender_name or profile.sender_name,
            from_address=settings.email_from_address,
            headers={
                # One-click opt-out for clients that honour it, which keeps the
                # unsubscribe working even if the footer link is never clicked.
                "List-Unsubscribe": f"<{unsubscribe_url(campaign_lead.unsubscribe_token)}>",
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
            },
        )
    except Exception as exc:
        message.status = MessageStatus.FAILED
        message.error = str(exc)[:500]
        db.flush()
        record_event(
            db,
            lead=lead,
            event_type=EmailEventType.FAILED,
            campaign_id=campaign_lead.campaign_id,
            message_id=message.id,
            metadata={"error": message.error},
        )
        raise

    message.status = MessageStatus.SENT
    message.sent_at = datetime.now(UTC)
    message.provider_message_id = sent.provider_message_id
    db.flush()

    record_event(
        db,
        lead=lead,
        event_type=EmailEventType.SENT,
        campaign_id=campaign_lead.campaign_id,
        message_id=message.id,
        metadata={"provider": sent.provider, "provider_message_id": sent.provider_message_id},
    )
    # The provider accepted it. A real deliverability webhook would confirm
    # this independently; with none wired up, acceptance is the best signal
    # available and is recorded as its own event rather than merged into SENT.
    record_event(
        db,
        lead=lead,
        event_type=EmailEventType.DELIVERED,
        campaign_id=campaign_lead.campaign_id,
        message_id=message.id,
        metadata={"source": "provider_accepted"},
    )
    return message
