"""Recording email events.

Every event in the system goes through `record_event`, which is also the only
place a score recompute is triggered. That single entry point is why the
tracking pixel, the manual event endpoint and the reply flow cannot drift apart
in how they update a lead.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import EmailEvent, Lead
from app.models.enums import EmailEventType
from app.services.lead_scores import apply_score

logger = get_logger(__name__)

#: Human-readable reasons written into score_history, so the console timeline
#: reads as prose rather than enum values.
EVENT_REASONS: dict[EmailEventType, str] = {
    EmailEventType.QUEUED: "Queued for sending",
    EmailEventType.SENT: "Outreach email sent",
    EmailEventType.DELIVERED: "Email delivered",
    EmailEventType.OPENED: "Email opened",
    EmailEventType.CLICKED: "Link clicked",
    EmailEventType.REPLIED: "Reply received",
    EmailEventType.BOUNCED: "Email bounced",
    EmailEventType.UNSUBSCRIBED: "Lead unsubscribed",
    EmailEventType.FAILED: "Send failed",
}


def record_event(
    db: Session,
    *,
    lead: Lead,
    event_type: EmailEventType,
    campaign_id: UUID | None = None,
    message_id: UUID | None = None,
    occurred_at: datetime | None = None,
    metadata: dict[str, Any] | None = None,
    reason: str | None = None,
) -> EmailEvent:
    """Append an event and recompute the lead's score from the full history."""
    event = EmailEvent(
        lead_id=lead.id,
        campaign_id=campaign_id,
        message_id=message_id,
        event_type=event_type,
        event_metadata=metadata or {},
    )
    if occurred_at is not None:
        event.occurred_at = occurred_at

    db.add(event)
    # Flushed before scoring so the new row is visible to the engine's query
    # and so score_history can reference the event that caused the change.
    db.flush()

    apply_score(db, lead, reason=reason or EVENT_REASONS.get(event_type, str(event_type)), trigger_event=event)
    logger.info("event %s recorded for lead %s", event_type, lead.id)
    return event
