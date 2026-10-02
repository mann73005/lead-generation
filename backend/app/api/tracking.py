"""Open tracking and unsubscribe.

Both routes are deliberately unauthenticated and live outside /api/v1: they are
fetched by a recipient's mail client and clicked from an inbox, neither of
which carries a bearer token. The opaque per-message and per-campaign-lead
tokens are what authorise them.
"""

import base64
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession
from app.core.logging import get_logger
from app.models import CampaignLead, EmailEvent, EmailMessage
from app.models.enums import EmailEventType, SuppressionReason
from app.services.events import record_event
from app.services.suppression import suppress

logger = get_logger(__name__)
router = APIRouter(tags=["tracking"])

#: 1x1 transparent PNG.
PIXEL = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)

PIXEL_HEADERS = {
    # Mail clients and their proxies cache aggressively; without this a second
    # open is served from cache and never reaches us.
    "Cache-Control": "no-store, no-cache, must-revalidate, private",
    "Pragma": "no-cache",
    "Expires": "0",
}

#: Opens closer together than this are treated as one. Gmail fetches images
#: through a proxy that may request the same pixel several times in quick
#: succession, which is a transport artefact rather than the lead reading the
#: mail twice.
OPEN_DEDUPE_WINDOW = timedelta(seconds=10)


def _pixel() -> Response:
    return Response(content=PIXEL, media_type="image/png", headers=PIXEL_HEADERS)


@router.get("/t/{token}.png", include_in_schema=False)
def track_open(token: str, request: Request, db: DbSession) -> Response:
    """Record an open and return the pixel.

    The pixel is returned no matter what — unknown token, duplicate request,
    anything. A broken image in a prospect's inbox is a worse outcome than a
    missed statistic, and a 404 here would tell a scanner which tokens exist.
    """
    message = db.scalar(
        select(EmailMessage)
        .where(EmailMessage.tracking_token == token)
        .options(
            selectinload(EmailMessage.campaign_lead)
            .selectinload(CampaignLead.lead)
        )
    )
    if message is None:
        logger.info("open pixel requested with an unknown token")
        return _pixel()

    last_open = db.scalar(
        select(EmailEvent)
        .where(
            EmailEvent.message_id == message.id,
            EmailEvent.event_type == EmailEventType.OPENED,
        )
        .order_by(EmailEvent.occurred_at.desc())
        .limit(1)
    )
    if last_open and datetime.now(UTC) - last_open.occurred_at < OPEN_DEDUPE_WINDOW:
        return _pixel()

    record_event(
        db,
        lead=message.campaign_lead.lead,
        event_type=EmailEventType.OPENED,
        campaign_id=message.campaign_lead.campaign_id,
        message_id=message.id,
        metadata={
            "user_agent": request.headers.get("user-agent", "")[:300],
            "first_open": not message.pixel_fired,
        },
    )
    message.pixel_fired = True
    return _pixel()


@router.get("/u/{token}", response_class=HTMLResponse, include_in_schema=False)
def unsubscribe(token: str, db: DbSession) -> HTMLResponse:
    """Honour an opt-out: suppress the address and record the event."""
    campaign_lead = db.scalar(
        select(CampaignLead)
        .where(CampaignLead.unsubscribe_token == token)
        .options(selectinload(CampaignLead.lead))
    )
    if campaign_lead is None:
        return HTMLResponse(_page("This unsubscribe link is not valid."), status_code=404)

    lead = campaign_lead.lead

    # Both addresses are suppressed: the lead's own, and the inbox the message
    # was actually delivered to. Opting out from a redirected copy must still
    # stop the mail arriving.
    from app.core.config import settings

    for address in {lead.email, settings.email_override_to}:
        if address:
            suppress(db, address, reason=SuppressionReason.UNSUBSCRIBED, lead_id=lead.id)

    record_event(
        db,
        lead=lead,
        event_type=EmailEventType.UNSUBSCRIBED,
        campaign_id=campaign_lead.campaign_id,
        metadata={"via": "unsubscribe_link"},
    )
    logger.info("lead %s unsubscribed", lead.id)
    return HTMLResponse(
        _page(
            "You have been unsubscribed.",
            "We will not contact you again. Nothing further is required from you.",
        )
    )


def _page(heading: str, detail: str = "") -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{heading}</title>
<meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;
             background:#f7f8fa;color:#1f2430;display:flex;align-items:center;
             justify-content:center;min-height:100vh;margin:0;">
  <main style="background:#fff;border:1px solid #e5e7eb;border-radius:12px;
               padding:40px;max-width:420px;text-align:center;">
    <h1 style="font-size:18px;margin:0 0 8px;">{heading}</h1>
    <p style="font-size:14px;color:#6b7280;margin:0;line-height:1.6;">{detail}</p>
  </main>
</body></html>"""
