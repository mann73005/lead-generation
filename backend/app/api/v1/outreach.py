"""Outreach routes: generate a grounded draft, then send it."""

from uuid import UUID

from fastapi import APIRouter, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession, Pagination
from app.core.exceptions import ConflictError, NotFoundError
from app.models import Campaign, CampaignLead, EmailMessage, Lead
from app.models.enums import MessageStatus
from app.schemas.campaign import MessageOut
from app.schemas.common import Page
from app.services.outreach import generate_message, send_message

router = APIRouter(tags=["outreach"])


def _load_campaign_lead(db: DbSession, campaign_id: UUID, lead_id: UUID) -> CampaignLead:
    campaign_lead = db.scalar(
        select(CampaignLead)
        .where(CampaignLead.campaign_id == campaign_id, CampaignLead.lead_id == lead_id)
        .options(
            selectinload(CampaignLead.lead).selectinload(Lead.company),
            selectinload(CampaignLead.campaign),
        )
    )
    if campaign_lead is None:
        raise NotFoundError(
            "That lead is not part of this campaign",
            details={"campaign_id": str(campaign_id), "lead_id": str(lead_id)},
        )
    return campaign_lead


def _load_message(db: DbSession, message_id: UUID) -> EmailMessage:
    message = db.scalar(
        select(EmailMessage)
        .where(EmailMessage.id == message_id)
        .options(
            selectinload(EmailMessage.campaign_lead).selectinload(CampaignLead.lead),
            selectinload(EmailMessage.campaign_lead).selectinload(CampaignLead.campaign),
        )
    )
    if message is None:
        raise NotFoundError(f"Message {message_id} does not exist")
    return message


@router.post(
    "/campaigns/{campaign_id}/leads/{lead_id}/messages",
    response_model=MessageOut,
    status_code=status.HTTP_201_CREATED,
)
def create_draft(campaign_id: UUID, lead_id: UUID, db: DbSession, _: CurrentUser) -> EmailMessage:
    """Compose a draft from stored data. Nothing is sent.

    Returns the grounding report and the list of sentences that were dropped
    alongside the copy, so the salesperson can see what the system refused to
    claim before they approve it.
    """
    return generate_message(db, _load_campaign_lead(db, campaign_id, lead_id))


@router.post("/messages/{message_id}/send", response_model=MessageOut)
def send(message_id: UUID, db: DbSession, _: CurrentUser) -> EmailMessage:
    """Send a draft through the configured provider.

    Fails with 409 if the recipient has unsubscribed — the suppression check is
    inside the send path, so there is no way to reach the provider around it.
    """
    message = _load_message(db, message_id)
    if message.status == MessageStatus.SENT:
        raise ConflictError(
            "This message has already been sent",
            details={"sent_at": message.sent_at.isoformat() if message.sent_at else None},
        )
    return send_message(db, message)


@router.get("/messages/{message_id}", response_model=MessageOut)
def read_message(message_id: UUID, db: DbSession, _: CurrentUser) -> EmailMessage:
    return _load_message(db, message_id)


@router.get("/campaigns/{campaign_id}/messages", response_model=Page[MessageOut])
def list_campaign_messages(
    campaign_id: UUID, db: DbSession, _: CurrentUser, page: Pagination
) -> Page[MessageOut]:
    if db.get(Campaign, campaign_id) is None:
        raise NotFoundError(f"Campaign {campaign_id} does not exist")

    campaign_lead_ids = select(CampaignLead.id).where(CampaignLead.campaign_id == campaign_id)
    total = (
        db.scalar(
            select(func.count(EmailMessage.id)).where(
                EmailMessage.campaign_lead_id.in_(campaign_lead_ids)
            )
        )
        or 0
    )
    rows = db.scalars(
        select(EmailMessage)
        .where(EmailMessage.campaign_lead_id.in_(campaign_lead_ids))
        .order_by(EmailMessage.created_at.desc())
        .limit(page.limit)
        .offset(page.offset)
    )
    return Page.build([MessageOut.model_validate(r) for r in rows], total, page)
