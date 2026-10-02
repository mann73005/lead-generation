"""Controlled vocabularies shared by the ORM models and API schemas.

These are stored as VARCHAR + CHECK constraints rather than native PostgreSQL
ENUM types: adding a value to a native enum requires an `ALTER TYPE` migration
that cannot run inside a transaction, which makes routine schema changes
needlessly painful for a project this size.
"""

from enum import StrEnum


class LeadStatus(StrEnum):
    """Lifecycle position of a lead, derived from its email events."""

    NEW = "new"
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    OPENED = "opened"
    REPLIED = "replied"
    UNSUBSCRIBED = "unsubscribed"
    BOUNCED = "bounced"


#: Ranked weakest -> strongest. The derived status of a lead is the highest-
#: ranked status implied by any of its events.
LEAD_STATUS_RANK: dict[LeadStatus, int] = {
    LeadStatus.NEW: 0,
    LeadStatus.QUEUED: 1,
    LeadStatus.SENT: 2,
    LeadStatus.DELIVERED: 3,
    LeadStatus.OPENED: 4,
    LeadStatus.REPLIED: 5,
    LeadStatus.BOUNCED: 6,
    LeadStatus.UNSUBSCRIBED: 7,
}


class EmailEventType(StrEnum):
    """Immutable facts recorded against a lead.

    `CLICKED` is defined but never emitted: click tracking is explicitly out of
    core scope, and reserving the value keeps the schema stable if it is added.
    """

    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    OPENED = "opened"
    CLICKED = "clicked"
    REPLIED = "replied"
    BOUNCED = "bounced"
    UNSUBSCRIBED = "unsubscribed"
    FAILED = "failed"


#: Event -> the lead status it implies. Events absent from this map (FAILED,
#: CLICKED) record history without advancing the lifecycle.
EVENT_TO_STATUS: dict[EmailEventType, LeadStatus] = {
    EmailEventType.QUEUED: LeadStatus.QUEUED,
    EmailEventType.SENT: LeadStatus.SENT,
    EmailEventType.DELIVERED: LeadStatus.DELIVERED,
    EmailEventType.OPENED: LeadStatus.OPENED,
    EmailEventType.REPLIED: LeadStatus.REPLIED,
    EmailEventType.BOUNCED: LeadStatus.BOUNCED,
    EmailEventType.UNSUBSCRIBED: LeadStatus.UNSUBSCRIBED,
}


class CampaignStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"


class MessageStatus(StrEnum):
    DRAFT = "draft"
    SENT = "sent"
    FAILED = "failed"
    SUPPRESSED = "suppressed"


class ReplyIntent(StrEnum):
    """The classification label set fixed by the brief."""

    INTERESTED = "interested"
    NEEDS_INFO = "needs_info"
    NOT_NOW = "not_now"
    WRONG_PERSON = "wrong_person"
    UNSUBSCRIBE = "unsubscribe"


class SuppressionReason(StrEnum):
    UNSUBSCRIBED = "unsubscribed"
    BOUNCED = "bounced"
    MANUAL = "manual"
    REPLY_OPT_OUT = "reply_opt_out"


class DiscoveryRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
