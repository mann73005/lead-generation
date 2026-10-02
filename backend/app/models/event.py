"""Email events — the append-only fact table the whole system derives from."""

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin, enum_check
from app.models.enums import EmailEventType

if TYPE_CHECKING:
    from app.models.campaign import EmailMessage
    from app.models.lead import Lead


class EmailEvent(UUIDMixin, Base):
    """One thing that happened to one lead at one point in time.

    Rows are never updated or deleted. Scores, statuses and console filters are
    all projections of this table; if the scoring weights change tomorrow, the
    history is still intact and every score can be rebuilt.

    `occurred_at` is distinct from `created_at`: a provider webhook can report
    an event that happened before we recorded it, and ordering must follow when
    it happened, not when we heard about it.
    """

    __tablename__ = "email_events"

    lead_id: Mapped[UUID] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    campaign_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("campaigns.id", ondelete="SET NULL"), index=True
    )
    message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("email_messages.id", ondelete="SET NULL"), index=True
    )

    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    #: Provider payload, user agent, IP — whatever context the source gave us.
    #: Mapped to the column name "metadata"; the attribute is renamed because
    #: `metadata` is reserved on SQLAlchemy declarative classes.
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, nullable=False
    )

    lead: Mapped["Lead"] = relationship(back_populates="events")
    message: Mapped["EmailMessage | None"] = relationship(back_populates="events")

    __table_args__ = (
        enum_check("event_type", EmailEventType),
        # The scoring engine's hot path: every event for one lead, in order.
        Index("ix_email_events_lead_id_occurred_at", "lead_id", "occurred_at"),
    )

    def __repr__(self) -> str:
        return f"<EmailEvent {self.event_type} lead={self.lead_id}>"
