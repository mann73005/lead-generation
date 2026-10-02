"""Event routes.

Manual ingestion exists so the full lifecycle can be driven without waiting on
a real mail client, and so a provider webhook has an established shape to post
into later. It is the same code path the tracking pixel uses.
"""

from uuid import UUID

from fastapi import APIRouter, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession, Pagination
from app.core.exceptions import NotFoundError
from app.models import Campaign, EmailEvent, EmailMessage, Lead
from app.models.enums import EmailEventType
from app.schemas.common import Page
from app.schemas.event import EventCreate
from app.schemas.lead import EventOut
from app.services.events import record_event

router = APIRouter(prefix="/events", tags=["events"])


@router.post("", response_model=EventOut, status_code=status.HTTP_201_CREATED)
def create_event(payload: EventCreate, db: DbSession, _: CurrentUser) -> EmailEvent:
    lead = db.scalar(
        select(Lead).where(Lead.id == payload.lead_id).options(selectinload(Lead.company))
    )
    if lead is None:
        raise NotFoundError(f"Lead {payload.lead_id} does not exist")

    if payload.campaign_id and db.get(Campaign, payload.campaign_id) is None:
        raise NotFoundError(f"Campaign {payload.campaign_id} does not exist")
    if payload.message_id and db.get(EmailMessage, payload.message_id) is None:
        raise NotFoundError(f"Message {payload.message_id} does not exist")

    return record_event(
        db,
        lead=lead,
        event_type=payload.event_type,
        campaign_id=payload.campaign_id,
        message_id=payload.message_id,
        occurred_at=payload.occurred_at,
        metadata=payload.metadata,
    )


@router.get("", response_model=Page[EventOut])
def list_events(
    db: DbSession,
    _: CurrentUser,
    page: Pagination,
    lead_id: UUID | None = None,
    campaign_id: UUID | None = None,
    event_type: EmailEventType | None = Query(default=None),
) -> Page[EventOut]:
    stmt = select(EmailEvent)
    count_stmt = select(func.count(EmailEvent.id))

    for condition in (
        EmailEvent.lead_id == lead_id if lead_id else None,
        EmailEvent.campaign_id == campaign_id if campaign_id else None,
        EmailEvent.event_type == event_type if event_type else None,
    ):
        if condition is not None:
            stmt = stmt.where(condition)
            count_stmt = count_stmt.where(condition)

    total = db.scalar(count_stmt) or 0
    rows = db.scalars(
        stmt.order_by(EmailEvent.occurred_at.desc()).limit(page.limit).offset(page.offset)
    )
    return Page.build([EventOut.model_validate(r) for r in rows], total, page)
