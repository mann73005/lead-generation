"""Persistence layer around the scoring engine.

`app.services.scoring` decides what a score should be; this module decides what
to write down. Keeping them apart is what lets the engine stay a pure function
with tests that never touch a database.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.logging import get_logger
from app.models import (
    ICP,
    Campaign,
    CampaignLead,
    EmailEvent,
    Lead,
    LeadScore,
    Reply,
    ScoreHistory,
)
from app.services.scoring import ScoreResult, compute_score

logger = get_logger(__name__)


def resolve_icp(db: Session, lead: Lead) -> ICP | None:
    """Find the ICP a lead should be scored against.

    Preference order:
      1. the ICP that discovered it — the criteria it was actually sourced for;
      2. the ICP of a campaign it belongs to, for manually added leads;
      3. none, in which case fit scores zero and only engagement counts.
    """
    if lead.discovery_run_id:
        icp = db.scalar(
            select(ICP).join(ICP.runs).where(ICP.runs.any(id=lead.discovery_run_id))
        )
        if icp:
            return icp

    return db.scalar(
        select(ICP)
        .join(Campaign, Campaign.icp_id == ICP.id)
        .join(CampaignLead, CampaignLead.campaign_id == Campaign.id)
        .where(CampaignLead.lead_id == lead.id)
        .order_by(Campaign.created_at)
        .limit(1)
    )


def latest_reply_intent(db: Session, lead_id: UUID) -> str | None:
    """Most recent classified intent — later replies supersede earlier ones."""
    return db.scalar(
        select(Reply.intent).where(Reply.lead_id == lead_id).order_by(Reply.created_at.desc()).limit(1)
    )


def calculate(db: Session, lead: Lead) -> ScoreResult:
    """Score a lead from scratch, reading everything the engine needs."""
    events = list(db.scalars(select(EmailEvent).where(EmailEvent.lead_id == lead.id)))
    return compute_score(
        lead=lead,
        company=lead.company,
        icp=resolve_icp(db, lead),
        events=events,
        reply_intent=latest_reply_intent(db, lead.id),
    )


def apply_score(
    db: Session,
    lead: Lead,
    *,
    reason: str,
    trigger_event: EmailEvent | None = None,
) -> LeadScore:
    """Recompute, persist, and append to history when the number moved.

    History is only appended on an actual change. An event that leaves the
    score untouched is still recorded in `email_events` — duplicating it in
    `score_history` would turn the lead's "why did this change" timeline into
    noise.
    """
    result = calculate(db, lead)

    score = db.scalar(select(LeadScore).where(LeadScore.lead_id == lead.id))
    previous: int | None = score.total_score if score else None

    if score is None:
        score = LeadScore(lead_id=lead.id)
        db.add(score)

    score.fit_score = result.fit_score
    score.engagement_score = result.engagement_score
    score.total_score = result.total_score
    score.status = result.status
    score.breakdown = result.breakdown
    score.computed_at = datetime.now(UTC)

    if previous != result.total_score:
        db.add(
            ScoreHistory(
                lead_id=lead.id,
                trigger_event_id=trigger_event.id if trigger_event else None,
                old_score=previous,
                new_score=result.total_score,
                delta=result.total_score - (previous or 0),
                reason=reason,
                breakdown=result.breakdown,
            )
        )
        logger.info(
            "score %s: %s -> %s (%s)", lead.id, previous, result.total_score, reason
        )

    db.flush()
    return score


def rebuild_all_scores(db: Session) -> int:
    """Recompute every lead from its event history.

    This is the operation the brief's event/derived-state split exists for:
    after changing `config/scoring.yaml`, run this and the whole list re-ranks
    with no loss of history. Exposed through `scripts/rebuild_scores.py`.
    """
    leads = list(
        db.scalars(select(Lead).options(selectinload(Lead.company)).order_by(Lead.created_at))
    )
    for lead in leads:
        apply_score(db, lead, reason="Score rebuilt from event history")
    return len(leads)
