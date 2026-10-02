"""Lead routes — the console's main data source."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, status
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import CurrentUser, DbSession, Pagination
from app.core.exceptions import ConflictError, NotFoundError
from app.models import Campaign, CampaignLead, Company, Lead, LeadScore
from app.models.enums import LeadStatus
from app.schemas.common import Page
from app.schemas.lead import LeadCreate, LeadDetailOut, LeadOut, LeadUpdate
from app.services.lead_scores import apply_score

router = APIRouter(prefix="/leads", tags=["leads"])

SortField = Literal["score", "created_at", "name"]


def _visible(stmt: Select, user) -> Select:
    """Restrict a lead query to what this user may see.

    Applied in one helper rather than at each call site: a route that
    forgets the filter leaks another salesperson's pipeline, and that is
    not the kind of thing to leave to discipline.
    """
    return stmt if user.is_admin else stmt.where(Lead.owner_id == user.id)


def _get_lead(db: Session, lead_id: UUID, user, *, detail: bool = False) -> Lead:
    stmt = _visible(select(Lead).where(Lead.id == lead_id), user).options(
        selectinload(Lead.company), selectinload(Lead.score)
    )
    if detail:
        stmt = stmt.options(selectinload(Lead.events), selectinload(Lead.score_history))

    # Relationships are refreshed rather than served from the identity map:
    # a request that records an event and then re-reads the lead in the same
    # session must see the event it just wrote.
    lead = db.scalar(stmt.execution_options(populate_existing=True))
    if lead is None:
        raise NotFoundError(f"Lead {lead_id} does not exist", details={"lead_id": str(lead_id)})
    return lead


def _apply_filters(
    stmt: Select,
    *,
    q: str | None,
    industry: str | None,
    region: str | None,
    lead_status: LeadStatus | None,
    min_score: int | None,
    max_score: int | None,
    campaign_id: UUID | None,
) -> Select:
    if q:
        term = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Lead.first_name.ilike(term),
                Lead.last_name.ilike(term),
                Lead.job_title.ilike(term),
                Lead.email.ilike(term),
                Company.name.ilike(term),
            )
        )
    if industry:
        stmt = stmt.where(Company.industry.ilike(f"%{industry}%"))
    if region:
        stmt = stmt.where(Company.region.ilike(f"%{region}%"))
    if lead_status is not None:
        stmt = stmt.where(LeadScore.status == lead_status)
    if min_score is not None:
        stmt = stmt.where(LeadScore.total_score >= min_score)
    if max_score is not None:
        stmt = stmt.where(LeadScore.total_score <= max_score)
    if campaign_id is not None:
        stmt = stmt.where(
            Lead.id.in_(select(CampaignLead.lead_id).where(CampaignLead.campaign_id == campaign_id))
        )
    return stmt


@router.get("", response_model=Page[LeadOut])
def list_leads(
    db: DbSession,
    user: CurrentUser,
    page: Pagination,
    q: Annotated[str | None, Query(max_length=120, description="Name, title, email or company.")] = None,
    industry: Annotated[str | None, Query(max_length=120)] = None,
    region: Annotated[str | None, Query(max_length=120)] = None,
    lead_status: Annotated[LeadStatus | None, Query(alias="status")] = None,
    min_score: Annotated[int | None, Query(ge=0, le=100)] = None,
    max_score: Annotated[int | None, Query(ge=0, le=100)] = None,
    campaign_id: UUID | None = None,
    sort: SortField = "score",
    order: Literal["asc", "desc"] = "desc",
) -> Page[LeadOut]:
    """Ranked, filtered lead list.

    LEFT JOINs onto `lead_scores` rather than INNER: a lead whose score has not
    been computed yet must still appear in the console, at the bottom, instead
    of vanishing from the list.
    """
    filters = {
        "q": q,
        "industry": industry,
        "region": region,
        "lead_status": lead_status,
        "min_score": min_score,
        "max_score": max_score,
        "campaign_id": campaign_id,
    }

    base = select(Lead).join(Company, Lead.company_id == Company.id).outerjoin(
        LeadScore, LeadScore.lead_id == Lead.id
    )

    total = db.scalar(
        _apply_filters(
            select(func.count(Lead.id))
            .select_from(Lead)
            .join(Company, Lead.company_id == Company.id)
            .outerjoin(LeadScore, LeadScore.lead_id == Lead.id),
            **filters,
        ).where(*([] if user.is_admin else [Lead.owner_id == user.id]))
    ) or 0

    columns = {
        "score": LeadScore.total_score,
        "created_at": Lead.created_at,
        "name": Lead.first_name,
    }
    column = columns[sort]
    # nulls_last on both directions so unscored leads never occupy the top of
    # the list just because their score is NULL.
    ordering = column.desc().nulls_last() if order == "desc" else column.asc().nulls_last()

    stmt = (
        _visible(_apply_filters(base, **filters), user)
        .options(selectinload(Lead.company), selectinload(Lead.score))
        .order_by(ordering, Lead.id)
        .limit(page.limit)
        .offset(page.offset)
    )

    return Page.build([LeadOut.model_validate(lead) for lead in db.scalars(stmt)], total, page)


@router.get("/{lead_id}", response_model=LeadDetailOut)
def get_lead(lead_id: UUID, db: DbSession, user: CurrentUser) -> Lead:
    return _get_lead(db, lead_id, user, detail=True)


@router.post("", response_model=LeadOut, status_code=status.HTTP_201_CREATED)
def create_lead(payload: LeadCreate, db: DbSession, user: CurrentUser) -> Lead:
    company = db.get(Company, payload.company_id)
    if company is None:
        raise NotFoundError(f"Company {payload.company_id} does not exist")

    duplicate = db.scalar(
        select(Lead).where(Lead.company_id == payload.company_id, Lead.email == payload.email)
    )
    if payload.email and duplicate:
        raise ConflictError(
            "A lead with this email already exists at this company",
            details={"existing_lead_id": str(duplicate.id)},
        )

    lead = Lead(**payload.model_dump(), owner_id=user.id)
    db.add(lead)
    db.flush()

    # Scored immediately so it is rankable the moment it appears, rather than
    # sitting at the bottom of the console until its first email event.
    apply_score(db, lead, reason="Lead created")
    db.refresh(lead)
    return lead


@router.patch("/{lead_id}", response_model=LeadOut)
def update_lead(lead_id: UUID, payload: LeadUpdate, db: DbSession, user: CurrentUser) -> Lead:
    lead = _get_lead(db, lead_id, user)

    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(lead, field, value)
    db.flush()

    # Editing a title or adding an email changes the fit score, so the lead is
    # rescored rather than left showing a number from before the edit.
    if updates:
        apply_score(db, lead, reason="Lead details updated")
    db.refresh(lead)
    return lead


@router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_lead(lead_id: UUID, db: DbSession, user: CurrentUser) -> None:
    lead = _get_lead(db, lead_id, user)
    db.delete(lead)


@router.post("/{lead_id}/rescore", response_model=LeadOut)
def rescore_lead(lead_id: UUID, db: DbSession, user: CurrentUser) -> Lead:
    """Force a recompute from event history.

    Useful after editing `config/scoring.yaml`, and the clearest demonstration
    that scores are derived rather than stored progressively.
    """
    lead = _get_lead(db, lead_id, user)
    apply_score(db, lead, reason="Manual rescore")
    db.refresh(lead)
    return lead
