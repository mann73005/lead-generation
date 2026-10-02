"""ORM models.

Every model is re-exported here so that importing `app.models` is enough to
register the full metadata with the declarative base — which is what Alembic's
autogenerate relies on to see the whole schema.
"""

from app.models.base import Base
from app.models.campaign import Campaign, CampaignLead, EmailMessage
from app.models.company import Company
from app.models.enums import (
    EVENT_TO_STATUS,
    LEAD_STATUS_RANK,
    CampaignStatus,
    DiscoveryRunStatus,
    EmailEventType,
    LeadStatus,
    MessageStatus,
    ReplyIntent,
    SuppressionReason,
)
from app.models.event import EmailEvent
from app.models.icp import ICP, DiscoveryRun
from app.models.lead import Lead, LeadScore, ScoreHistory
from app.models.product import ProductProfile
from app.models.reply import Reply
from app.models.suppression import SuppressedEmail
from app.models.user import User

__all__ = [
    "EVENT_TO_STATUS",
    "ICP",
    "LEAD_STATUS_RANK",
    "Base",
    "Campaign",
    "CampaignLead",
    "CampaignStatus",
    "Company",
    "DiscoveryRun",
    "DiscoveryRunStatus",
    "EmailEvent",
    "EmailEventType",
    "EmailMessage",
    "Lead",
    "LeadScore",
    "LeadStatus",
    "MessageStatus",
    "ProductProfile",
    "Reply",
    "ReplyIntent",
    "ScoreHistory",
    "SuppressedEmail",
    "SuppressionReason",
    "User",
]
