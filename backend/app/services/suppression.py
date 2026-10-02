"""The suppression list.

Checked before every send, with no way to bypass it: `outreach.send_message` is
the only path to the provider and it consults this first. The brief calls the
unsubscribe path non-negotiable, so the check lives in the send path rather
than in a caller that might forget.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import SuppressedEmail
from app.models.enums import SuppressionReason

logger = get_logger(__name__)


def normalise(email: str) -> str:
    return email.strip().lower()


def is_suppressed(db: Session, email: str | None) -> bool:
    if not email:
        return False
    return (
        db.scalar(
            select(func.count(SuppressedEmail.id)).where(
                SuppressedEmail.email == normalise(email)
            )
        )
        or 0
    ) > 0


def suppress(
    db: Session,
    email: str,
    *,
    reason: SuppressionReason,
    lead_id: UUID | None = None,
    notes: str | None = None,
) -> SuppressedEmail:
    """Add an address to the list. Idempotent — opting out twice is not an error."""
    address = normalise(email)
    existing = db.scalar(select(SuppressedEmail).where(SuppressedEmail.email == address))
    if existing:
        return existing

    record = SuppressedEmail(
        email=address, reason=reason, source_lead_id=lead_id, notes=notes
    )
    db.add(record)
    db.flush()
    logger.info("suppressed %s (%s)", address, reason)
    return record
