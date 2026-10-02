"""Version 1 of the REST API."""

from fastapi import APIRouter

from app.api.v1 import (
    auth,
    campaigns,
    companies,
    dashboard,
    discovery,
    events,
    icps,
    leads,
    outreach,
    product,
    replies,
    users,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(dashboard.router)
api_router.include_router(product.router)
api_router.include_router(icps.router)
api_router.include_router(discovery.router)
api_router.include_router(companies.router)
api_router.include_router(leads.router)
api_router.include_router(campaigns.router)
api_router.include_router(outreach.router)
api_router.include_router(replies.router)
api_router.include_router(events.router)

__all__ = ["api_router"]
