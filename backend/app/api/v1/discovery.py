"""Lead discovery routes.

Runs synchronously, which the brief explicitly permits for core scope. A run
takes tens of seconds, so the console shows a progress state rather than
pretending it is instant; moving this behind a job queue is a stretch item.
"""

from uuid import UUID

from fastapi import APIRouter, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.ai.discovery import run_discovery
from app.api.deps import CurrentUser, DbSession, Pagination
from app.core.exceptions import NotFoundError
from app.models import ICP, DiscoveryRun
from app.schemas.common import Page
from app.schemas.icp import DiscoveryRunDetailOut, DiscoveryRunOut

router = APIRouter(prefix="/discovery", tags=["discovery"])


class DiscoveryRequest(BaseModel):
    icp_id: UUID
    count: int = Field(default=8, ge=1, le=15, description="Target number of leads.")


@router.post("/run", response_model=DiscoveryRunOut, status_code=status.HTTP_201_CREATED)
def start_run(payload: DiscoveryRequest, db: DbSession, user: CurrentUser) -> DiscoveryRun:
    icp = db.get(ICP, payload.icp_id)
    if icp is None or (not user.is_admin and icp.owner_id != user.id):
        raise NotFoundError(f"ICP {payload.icp_id} does not exist")

    # A failed run is persisted with its error and transcript rather than
    # raising: a run that found nothing is a result the console should show,
    # not a 500 that loses the evidence of what the agent tried.
    return run_discovery(db, icp, requested_count=payload.count)


@router.get("/runs", response_model=Page[DiscoveryRunOut])
def list_runs(
    db: DbSession, _: CurrentUser, page: Pagination, icp_id: UUID | None = None
) -> Page[DiscoveryRunOut]:
    stmt = select(DiscoveryRun)
    count_stmt = select(func.count(DiscoveryRun.id))
    if icp_id:
        stmt = stmt.where(DiscoveryRun.icp_id == icp_id)
        count_stmt = count_stmt.where(DiscoveryRun.icp_id == icp_id)

    total = db.scalar(count_stmt) or 0
    rows = db.scalars(
        stmt.order_by(DiscoveryRun.created_at.desc()).limit(page.limit).offset(page.offset)
    )
    return Page.build([DiscoveryRunOut.model_validate(r) for r in rows], total, page)


@router.get("/runs/{run_id}", response_model=DiscoveryRunDetailOut)
def get_run(run_id: UUID, db: DbSession, _: CurrentUser) -> DiscoveryRun:
    """Includes the full tool transcript — which queries ran, which pages were
    read, and why each rejected candidate was rejected."""
    run = db.get(DiscoveryRun, run_id)
    if run is None:
        raise NotFoundError(f"Discovery run {run_id} does not exist")
    return run
