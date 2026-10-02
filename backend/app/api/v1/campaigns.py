"""Campaign routes."""

from uuid import UUID

from fastapi import APIRouter, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession, Pagination
from app.core.exceptions import NotFoundError
from app.models import ICP, Campaign, CampaignLead, EmailEvent, Lead
from app.models.enums import EmailEventType
from app.schemas.campaign import (
    AddLeadsRequest,
    CampaignCreate,
    CampaignOut,
    CampaignStatsOut,
    CampaignUpdate,
)
from app.schemas.common import Page
from app.schemas.lead import LeadOut

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


def _get_campaign(db: Session, campaign_id: UUID) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise NotFoundError(f"Campaign {campaign_id} does not exist")
    return campaign


def _distinct_lead_count(db: Session, campaign_id: UUID, event_type: EmailEventType) -> int:
    """Leads, not events — three opens from one person is one engaged lead."""
    return db.scalar(
        select(func.count(func.distinct(EmailEvent.lead_id))).where(
            EmailEvent.campaign_id == campaign_id, EmailEvent.event_type == event_type
        )
    ) or 0


def _with_stats(db: Session, campaign: Campaign) -> CampaignStatsOut:
    lead_count = db.scalar(
        select(func.count(CampaignLead.id)).where(CampaignLead.campaign_id == campaign.id)
    ) or 0
    return CampaignStatsOut(
        **CampaignOut.model_validate(campaign).model_dump(),
        lead_count=lead_count,
        sent_count=_distinct_lead_count(db, campaign.id, EmailEventType.SENT),
        opened_count=_distinct_lead_count(db, campaign.id, EmailEventType.OPENED),
        replied_count=_distinct_lead_count(db, campaign.id, EmailEventType.REPLIED),
    )


@router.post("", response_model=CampaignOut, status_code=status.HTTP_201_CREATED)
def create_campaign(payload: CampaignCreate, db: DbSession, _: CurrentUser) -> Campaign:
    if payload.icp_id is not None and db.get(ICP, payload.icp_id) is None:
        raise NotFoundError(f"ICP {payload.icp_id} does not exist")

    campaign = Campaign(**payload.model_dump())
    db.add(campaign)
    db.flush()
    return campaign


@router.get("", response_model=Page[CampaignStatsOut])
def list_campaigns(db: DbSession, _: CurrentUser, page: Pagination) -> Page[CampaignStatsOut]:
    total = db.scalar(select(func.count(Campaign.id))) or 0
    rows = db.scalars(
        select(Campaign).order_by(Campaign.created_at.desc()).limit(page.limit).offset(page.offset)
    )
    return Page.build([_with_stats(db, c) for c in rows], total, page)


@router.get("/{campaign_id}", response_model=CampaignStatsOut)
def get_campaign(campaign_id: UUID, db: DbSession, _: CurrentUser) -> CampaignStatsOut:
    return _with_stats(db, _get_campaign(db, campaign_id))


@router.patch("/{campaign_id}", response_model=CampaignOut)
def update_campaign(
    campaign_id: UUID, payload: CampaignUpdate, db: DbSession, _: CurrentUser
) -> Campaign:
    campaign = _get_campaign(db, campaign_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(campaign, field, value)
    db.flush()
    return campaign


@router.post("/{campaign_id}/leads", response_model=dict, status_code=status.HTTP_201_CREATED)
def add_leads(
    campaign_id: UUID, payload: AddLeadsRequest, db: DbSession, _: CurrentUser
) -> dict[str, int | list[str]]:
    """Add leads to a campaign, ignoring ones already in it.

    Idempotent by design: re-posting the same list is a no-op rather than a
    409, because the console's "add selected" button is easy to double-click.
    """
    campaign = _get_campaign(db, campaign_id)

    requested = set(payload.lead_ids)
    existing_ids = set(
        db.scalars(select(CampaignLead.lead_id).where(CampaignLead.campaign_id == campaign.id))
    )
    known_ids = set(db.scalars(select(Lead.id).where(Lead.id.in_(requested))))

    missing = sorted(str(i) for i in requested - known_ids)
    to_add = known_ids - existing_ids

    for lead_id in to_add:
        db.add(CampaignLead(campaign_id=campaign.id, lead_id=lead_id))
    db.flush()

    return {
        "added": len(to_add),
        "already_present": len(known_ids & existing_ids),
        "not_found": missing,
    }


@router.get("/{campaign_id}/leads", response_model=Page[LeadOut])
def list_campaign_leads(
    campaign_id: UUID, db: DbSession, _: CurrentUser, page: Pagination
) -> Page[LeadOut]:
    from sqlalchemy.orm import selectinload

    from app.models import LeadScore

    campaign = _get_campaign(db, campaign_id)
    lead_ids = select(CampaignLead.lead_id).where(CampaignLead.campaign_id == campaign.id)

    total = db.scalar(select(func.count(Lead.id)).where(Lead.id.in_(lead_ids))) or 0
    rows = db.scalars(
        select(Lead)
        .where(Lead.id.in_(lead_ids))
        .outerjoin(LeadScore, LeadScore.lead_id == Lead.id)
        .options(selectinload(Lead.company), selectinload(Lead.score))
        .order_by(LeadScore.total_score.desc().nulls_last(), Lead.id)
        .limit(page.limit)
        .offset(page.offset)
    )
    return Page.build([LeadOut.model_validate(r) for r in rows], total, page)
