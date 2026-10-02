"""Reply simulation, classification and approval."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.ai.classification import classify_reply
from app.api.deps import CurrentUser, DbSession, Pagination
from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError
from app.models import Campaign, EmailMessage, Lead, Reply
from app.models.enums import EmailEventType, ReplyIntent, SuppressionReason
from app.providers import get_llm_provider
from app.schemas.common import Page
from app.schemas.reply import ReplyApproval, ReplyCreate, ReplyOut
from app.services.events import record_event
from app.services.product_profile import get_active_profile
from app.services.suppression import suppress

router = APIRouter(prefix="/replies", tags=["replies"])


@router.post("", response_model=ReplyOut, status_code=status.HTTP_201_CREATED)
def simulate_reply(payload: ReplyCreate, db: DbSession, _: CurrentUser) -> Reply:
    """Classify a reply, draft an answer, and update the lead.

    The draft is stored unsent. Nothing in this system mails a reply on its
    own — `POST /replies/{id}/approve` is a separate, deliberate action.
    """
    lead = db.scalar(
        select(Lead).where(Lead.id == payload.lead_id).options(selectinload(Lead.company))
    )
    if lead is None:
        raise NotFoundError(f"Lead {payload.lead_id} does not exist")
    if payload.campaign_id and db.get(Campaign, payload.campaign_id) is None:
        raise NotFoundError(f"Campaign {payload.campaign_id} does not exist")
    if payload.message_id and db.get(EmailMessage, payload.message_id) is None:
        raise NotFoundError(f"Message {payload.message_id} does not exist")

    profile = get_active_profile(db)
    result = classify_reply(
        payload.text,
        lead=lead,
        company=lead.company,
        product=profile,
        sender_name=profile.sender_name,
        llm=get_llm_provider() if settings.llm_enabled else None,
    )

    reply = Reply(
        lead_id=lead.id,
        campaign_id=payload.campaign_id,
        message_id=payload.message_id,
        raw_text=payload.text,
        intent=result.intent,
        confidence=result.confidence,
        reasoning=result.reasoning,
        draft_response=result.draft_response,
        classifier_model=result.model,
    )
    db.add(reply)
    # Flushed before the event so the scoring engine, which reads the latest
    # classified intent, sees this one rather than the previous reply's.
    db.flush()

    record_event(
        db,
        lead=lead,
        event_type=EmailEventType.REPLIED,
        campaign_id=payload.campaign_id,
        message_id=payload.message_id,
        metadata={"intent": result.intent, "confidence": result.confidence},
        reason=f"Reply received — {result.intent.replace('_', ' ')}",
    )

    # A reply asking to stop is an opt-out however it arrived. Honouring it
    # only when someone clicks the footer link would be a compliance gap.
    if result.intent == ReplyIntent.UNSUBSCRIBE:
        for address in {lead.email, settings.email_override_to}:
            if address:
                suppress(
                    db,
                    address,
                    reason=SuppressionReason.REPLY_OPT_OUT,
                    lead_id=lead.id,
                    notes="Classified as an unsubscribe request",
                )
        record_event(
            db,
            lead=lead,
            event_type=EmailEventType.UNSUBSCRIBED,
            campaign_id=payload.campaign_id,
            metadata={"via": "reply_classification"},
        )

    return reply


@router.get("", response_model=Page[ReplyOut])
def list_replies(
    db: DbSession,
    _: CurrentUser,
    page: Pagination,
    lead_id: UUID | None = None,
    intent: ReplyIntent | None = None,
) -> Page[ReplyOut]:
    stmt = select(Reply)
    count_stmt = select(func.count(Reply.id))
    for condition in (
        Reply.lead_id == lead_id if lead_id else None,
        Reply.intent == intent if intent else None,
    ):
        if condition is not None:
            stmt = stmt.where(condition)
            count_stmt = count_stmt.where(condition)

    total = db.scalar(count_stmt) or 0
    rows = db.scalars(
        stmt.order_by(Reply.created_at.desc()).limit(page.limit).offset(page.offset)
    )
    return Page.build([ReplyOut.model_validate(r) for r in rows], total, page)


@router.post("/{reply_id}/approve", response_model=ReplyOut)
def approve_reply(
    reply_id: UUID, payload: ReplyApproval, db: DbSession, _: CurrentUser
) -> Reply:
    """Record that a human approved the drafted response.

    Approval is recorded, not acted on: outbound replies are out of scope, and
    an approval endpoint that quietly sent mail would be a surprising thing for
    a reviewer to find.
    """
    reply = db.get(Reply, reply_id)
    if reply is None:
        raise NotFoundError(f"Reply {reply_id} does not exist")
    if reply.approved:
        raise ConflictError("This reply has already been approved")

    if payload.draft_response is not None:
        reply.draft_response = payload.draft_response
    if not reply.draft_response:
        raise ConflictError("There is no drafted response to approve")

    reply.approved = True
    reply.approved_at = datetime.now(UTC)
    db.flush()
    return reply
