"""Simulated inbound replies and their AI classification."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin, enum_check
from app.models.enums import ReplyIntent

if TYPE_CHECKING:
    from app.models.lead import Lead


class Reply(UUIDMixin, TimestampMixin, Base):
    """A reply pasted into the console, classified and answered by the model.

    The drafted response is persisted unsent. Nothing in the system sends it
    automatically — `approved` must be set through an explicit user action,
    which is the human-in-the-loop step the brief asks for.
    """

    __tablename__ = "replies"

    lead_id: Mapped[UUID] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    campaign_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("campaigns.id", ondelete="SET NULL"), index=True
    )
    message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("email_messages.id", ondelete="SET NULL")
    )

    raw_text: Mapped[str] = mapped_column(Text, nullable=False)

    intent: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    confidence: Mapped[float | None] = mapped_column(Float)
    reasoning: Mapped[str | None] = mapped_column(Text)
    draft_response: Mapped[str | None] = mapped_column(Text)
    classifier_model: Mapped[str | None] = mapped_column(String(80))

    approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    lead: Mapped["Lead"] = relationship(back_populates="replies")

    __table_args__ = (
        enum_check("intent", ReplyIntent),
        CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1", name="confidence_in_range"
        ),
        CheckConstraint("(approved IS FALSE) OR (approved_at IS NOT NULL)", name="approval_timestamped"),
    )

    def __repr__(self) -> str:
        return f"<Reply {self.intent} lead={self.lead_id}>"
