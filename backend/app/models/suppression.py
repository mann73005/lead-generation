"""Suppression list — addresses that must never be sent to again."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin, enum_check
from app.models.enums import SuppressionReason


class SuppressedEmail(UUIDMixin, Base):
    """A hard block, checked before every send.

    Deliberately keyed on the address rather than the lead: the same person can
    exist as two leads under different companies, and an opt-out applies to the
    human, not the row. Suppression is global and permanent — there is no
    resubscribe path, which is the conservative reading of CAN-SPAM/GDPR.
    """

    __tablename__ = "suppressed_emails"

    #: Always stored lower-cased by the suppression service so lookups are
    #: a plain equality match on the unique index.
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    reason: Mapped[str] = mapped_column(String(20), nullable=False)
    source_lead_id: Mapped[UUID | None] = mapped_column(ForeignKey("leads.id", ondelete="SET NULL"))
    notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (enum_check("reason", SuppressionReason),)

    def __repr__(self) -> str:
        return f"<SuppressedEmail {self.email} {self.reason}>"
