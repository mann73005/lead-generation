"""Dashboard summary.

One request backs the whole landing screen. Members see their own pipeline;
admins see everything, plus per-user totals so they can tell who is working
the list.
"""

from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import Select, func, select

from app.api.deps import CurrentUser, DbSession
from app.models import EmailEvent, Lead, LeadScore, User
from app.models.enums import EmailEventType, LeadStatus
from app.services.scoring import load_scoring_config

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class StatusCount(BaseModel):
    status: LeadStatus
    count: int


class OwnerSummary(BaseModel):
    user_id: UUID | None
    email: str | None
    full_name: str | None
    leads: int
    hot: int


class DashboardOut(BaseModel):
    scope: str
    total_leads: int
    hot: int
    warm: int
    cold: int
    average_score: float
    by_status: list[StatusCount]
    emails_sent: int
    emails_opened: int
    replies: int
    unsubscribes: int
    #: Only populated for admins.
    by_owner: list[OwnerSummary]


def visible_leads(user: User) -> Select:
    """Base query scoped to what this user is allowed to see."""
    stmt = select(Lead.id)
    return stmt if user.is_admin else stmt.where(Lead.owner_id == user.id)


@router.get("", response_model=DashboardOut)
def read_dashboard(db: DbSession, user: CurrentUser) -> DashboardOut:
    bands = load_scoring_config().bands
    scope_ids = visible_leads(user).subquery()
    in_scope = Lead.id.in_(select(scope_ids.c.id))

    def count_scores(condition) -> int:
        return (
            db.scalar(
                select(func.count(LeadScore.id))
                .join(Lead, Lead.id == LeadScore.lead_id)
                .where(in_scope, condition)
            )
            or 0
        )

    def count_events(event_type: EmailEventType) -> int:
        # Distinct leads, not events: three opens from one person is one
        # engaged lead, and a funnel that double-counts is misleading.
        return (
            db.scalar(
                select(func.count(func.distinct(EmailEvent.lead_id)))
                .join(Lead, Lead.id == EmailEvent.lead_id)
                .where(in_scope, EmailEvent.event_type == event_type)
            )
            or 0
        )

    total = db.scalar(select(func.count(Lead.id)).where(in_scope)) or 0
    average = db.scalar(
        select(func.coalesce(func.avg(LeadScore.total_score), 0.0))
        .join(Lead, Lead.id == LeadScore.lead_id)
        .where(in_scope)
    )

    status_rows = db.execute(
        select(LeadScore.status, func.count(LeadScore.id))
        .join(Lead, Lead.id == LeadScore.lead_id)
        .where(in_scope)
        .group_by(LeadScore.status)
    ).all()

    by_owner: list[OwnerSummary] = []
    if user.is_admin:
        owner_rows = db.execute(
            select(
                Lead.owner_id,
                User.email,
                User.full_name,
                func.count(Lead.id),
                func.count(LeadScore.id).filter(LeadScore.total_score >= bands.hot),
            )
            .outerjoin(User, User.id == Lead.owner_id)
            .outerjoin(LeadScore, LeadScore.lead_id == Lead.id)
            .group_by(Lead.owner_id, User.email, User.full_name)
            .order_by(func.count(Lead.id).desc())
        ).all()
        by_owner = [
            OwnerSummary(
                user_id=row[0], email=row[1], full_name=row[2], leads=row[3], hot=row[4]
            )
            for row in owner_rows
        ]

    return DashboardOut(
        scope="all" if user.is_admin else "own",
        total_leads=total,
        hot=count_scores(LeadScore.total_score >= bands.hot),
        warm=count_scores(
            (LeadScore.total_score >= bands.warm) & (LeadScore.total_score < bands.hot)
        ),
        cold=count_scores(LeadScore.total_score < bands.warm),
        average_score=round(float(average or 0), 1),
        by_status=[StatusCount(status=s, count=c) for s, c in status_rows],
        emails_sent=count_events(EmailEventType.SENT),
        emails_opened=count_events(EmailEventType.OPENED),
        replies=count_events(EmailEventType.REPLIED),
        unsubscribes=count_events(EmailEventType.UNSUBSCRIBED),
        by_owner=by_owner,
    )
