"""Leads and their derived scoring state.

The brief requires raw events to be stored separately from derived state so
scores can be recomputed from history. That separation is physical here:

    leads          identity and ICP attributes  (facts about the person)
    email_events   immutable, append-only       (what happened)
    lead_scores    one row per lead             (derived; safe to delete and rebuild)
    score_history  append-only audit trail      (why the number moved)

Nothing writes to `lead_scores` except the scoring engine, and the engine is a
pure function of (lead, icp, events) — so dropping every row in `lead_scores`
and replaying the events reproduces the same numbers.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin, enum_check
from app.models.enums import LeadStatus

if TYPE_CHECKING:
    from app.models.campaign import CampaignLead
    from app.models.company import Company
    from app.models.event import EmailEvent
    from app.models.icp import DiscoveryRun
    from app.models.reply import Reply


class Lead(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "leads"

    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    discovery_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("discovery_runs.id", ondelete="SET NULL"), index=True
    )

    #: Denormalised from the ICP that discovered the lead, or set to the
    #: creating user. Stored on the row so the console can filter a large
    #: list without joining back through discovery_runs on every query.
    owner_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    first_name: Mapped[str] = mapped_column(String(120), nullable=False)
    last_name: Mapped[str | None] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(320))
    job_title: Mapped[str] = mapped_column(String(200), nullable=False)
    seniority: Mapped[str | None] = mapped_column(String(60))
    linkedin_url: Mapped[str | None] = mapped_column(Text)

    #: Required by the brief: every discovered lead carries the page it came
    #: from, and the grounding check will not cite anything else.
    source_url: Mapped[str] = mapped_column(Text, nullable=False)

    raw_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    company: Mapped["Company"] = relationship(back_populates="leads")
    discovery_run: Mapped["DiscoveryRun | None"] = relationship(back_populates="leads")
    score: Mapped["LeadScore | None"] = relationship(
        back_populates="lead", cascade="all, delete-orphan", passive_deletes=True, uselist=False
    )
    events: Mapped[list["EmailEvent"]] = relationship(
        back_populates="lead",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="EmailEvent.occurred_at",
    )
    score_history: Mapped[list["ScoreHistory"]] = relationship(
        back_populates="lead",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ScoreHistory.created_at",
    )
    campaign_links: Mapped[list["CampaignLead"]] = relationship(
        back_populates="lead", cascade="all, delete-orphan", passive_deletes=True
    )
    replies: Mapped[list["Reply"]] = relationship(
        back_populates="lead", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        # Allows the same person to appear once per company. NULL emails are
        # permitted and do not collide: discovery often finds a named decision
        # maker whose address is not public, and that lead is still worth
        # ranking even though it can never be sent to.
        UniqueConstraint("company_id", "email", name="uq_leads_company_id_email"),
        CheckConstraint("email IS NULL OR position('@' in email) > 1", name="email_shape"),
        Index("ix_leads_job_title", "job_title"),
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip() if self.last_name else self.first_name

    def __repr__(self) -> str:
        return f"<Lead {self.full_name!r} @ {self.company_id}>"


class LeadScore(UUIDMixin, TimestampMixin, Base):
    """Derived state. Recomputed in full on every event — never incremented.

    Deleting every row here loses no information: `rebuild_all_scores()`
    reconstructs it from `leads` + `icps` + `email_events`.
    """

    __tablename__ = "lead_scores"

    lead_id: Mapped[UUID] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    fit_score: Mapped[int] = mapped_column(default=0, nullable=False)
    engagement_score: Mapped[int] = mapped_column(default=0, nullable=False)
    total_score: Mapped[int] = mapped_column(default=0, nullable=False, index=True)

    #: Lifecycle position implied by the lead's events — also derived.
    status: Mapped[str] = mapped_column(String(20), default=LeadStatus.NEW, nullable=False, index=True)

    #: Per-component points, e.g. {"fit": {"industry_match": 25, ...}, ...}.
    #: Drives the score explanation panel in the console.
    breakdown: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    lead: Mapped["Lead"] = relationship(back_populates="score")

    __table_args__ = (
        CheckConstraint("total_score BETWEEN 0 AND 100", name="total_score_in_range"),
        CheckConstraint("fit_score >= 0 AND engagement_score >= 0", name="components_non_negative"),
        enum_check("status", LeadStatus),
    )

    def __repr__(self) -> str:
        return f"<LeadScore lead={self.lead_id} {self.total_score}>"


class ScoreHistory(UUIDMixin, Base):
    """Append-only record of why a score changed. Never updated or deleted."""

    __tablename__ = "score_history"

    lead_id: Mapped[UUID] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: The event that triggered the recompute, when there was one. Nullable
    #: because the first score is computed at creation, before any event.
    trigger_event_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("email_events.id", ondelete="SET NULL")
    )

    old_score: Mapped[int | None] = mapped_column()
    new_score: Mapped[int] = mapped_column(nullable=False)
    delta: Mapped[int] = mapped_column(nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    breakdown: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    lead: Mapped["Lead"] = relationship(back_populates="score_history")

    __table_args__ = (
        CheckConstraint("new_score BETWEEN 0 AND 100", name="new_score_in_range"),
    )

    def __repr__(self) -> str:
        return f"<ScoreHistory {self.old_score}->{self.new_score} {self.reason!r}>"
