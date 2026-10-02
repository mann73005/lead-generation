"""Campaigns, their lead membership, and the messages generated for them."""

import secrets
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin, enum_check
from app.models.enums import CampaignStatus, MessageStatus

if TYPE_CHECKING:
    from app.models.event import EmailEvent
    from app.models.icp import ICP
    from app.models.lead import Lead


def _token() -> str:
    """URL-safe, unguessable token for tracking and unsubscribe links."""
    return secrets.token_urlsafe(32)


class Campaign(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "campaigns"

    #: Who runs this campaign.
    owner_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    icp_id: Mapped[UUID | None] = mapped_column(ForeignKey("icps.id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(String(20), default=CampaignStatus.DRAFT, nullable=False)

    sender_name: Mapped[str] = mapped_column(String(120), nullable=False)
    sender_email: Mapped[str] = mapped_column(String(320), nullable=False)

    icp: Mapped["ICP | None"] = relationship()
    leads: Mapped[list["CampaignLead"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (enum_check("status", CampaignStatus),)

    def __repr__(self) -> str:
        return f"<Campaign {self.name!r} {self.status}>"


class CampaignLead(UUIDMixin, TimestampMixin, Base):
    """Membership of a lead in a campaign.

    A lead can belong to several campaigns, so per-campaign state (the
    unsubscribe token, whether this campaign has sent yet) lives here rather
    than on the lead.
    """

    __tablename__ = "campaign_leads"

    campaign_id: Mapped[UUID] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lead_id: Mapped[UUID] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True
    )

    #: Opting out of one campaign suppresses the address globally; this token
    #: is what the unsubscribe link carries so we know who clicked.
    unsubscribe_token: Mapped[str] = mapped_column(
        String(64), default=_token, nullable=False, unique=True
    )

    campaign: Mapped["Campaign"] = relationship(back_populates="leads")
    lead: Mapped["Lead"] = relationship(back_populates="campaign_links")
    messages: Mapped[list["EmailMessage"]] = relationship(
        back_populates="campaign_lead", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        UniqueConstraint("campaign_id", "lead_id", name="uq_campaign_leads_campaign_id_lead_id"),
    )

    def __repr__(self) -> str:
        return f"<CampaignLead c={self.campaign_id} l={self.lead_id}>"


class EmailMessage(UUIDMixin, TimestampMixin, Base):
    """A single generated outreach email.

    Stores not just the rendered copy but the provenance of every filled token
    and the grounding verdict, so a reviewer can answer "where did this
    sentence come from?" without re-running the model.
    """

    __tablename__ = "email_messages"

    campaign_lead_id: Mapped[UUID] = mapped_column(
        ForeignKey("campaign_leads.id", ondelete="CASCADE"), nullable=False, index=True
    )

    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    body_html: Mapped[str] = mapped_column(Text, nullable=False)

    #: token -> {"value", "source_url", "source_field", "verdict"}.
    tokens: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    #: Full output of the grounding check, including every rejection and why.
    grounding_report: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    #: Sentences removed because a required token could not be grounded.
    dropped_sentences: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)

    status: Mapped[str] = mapped_column(String(20), default=MessageStatus.DRAFT, nullable=False)

    #: Opaque id embedded in the open pixel URL. Per-message, not per-lead, so
    #: a second send to the same lead is attributable on its own.
    tracking_token: Mapped[str] = mapped_column(
        String(64), default=_token, nullable=False, unique=True, index=True
    )

    #: The address actually handed to the provider. Differs from the lead's
    #: stored email whenever EMAIL_OVERRIDE_TO is set, which is how discovered
    #: prospects are kept from ever receiving mail.
    to_address: Mapped[str | None] = mapped_column(String(320))
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    #: Set once the open pixel has been served for this message, so repeat
    #: image loads do not each count as a fresh first open.
    pixel_fired: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    campaign_lead: Mapped["CampaignLead"] = relationship(back_populates="messages")
    events: Mapped[list["EmailEvent"]] = relationship(back_populates="message")

    __table_args__ = (
        enum_check("status", MessageStatus),
        CheckConstraint(
            "(status <> 'sent') OR (sent_at IS NOT NULL)", name="sent_requires_timestamp"
        ),
    )

    def __repr__(self) -> str:
        return f"<EmailMessage {self.id} {self.status}>"
