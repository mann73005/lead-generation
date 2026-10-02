"""ICP routes — the targeting criteria that drive discovery and fit scoring."""

from uuid import UUID

from fastapi import APIRouter, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, Pagination
from app.core.exceptions import NotFoundError
from app.models import ICP
from app.schemas.common import Page
from app.schemas.icp import ICPCreate, ICPOut

router = APIRouter(prefix="/icps", tags=["icps"])


@router.post("", response_model=ICPOut, status_code=status.HTTP_201_CREATED)
def create_icp(payload: ICPCreate, db: DbSession, _: CurrentUser) -> ICP:
    icp = ICP(**payload.model_dump())
    db.add(icp)
    db.flush()
    return icp


@router.get("", response_model=Page[ICPOut])
def list_icps(db: DbSession, _: CurrentUser, page: Pagination) -> Page[ICPOut]:
    total = db.scalar(select(func.count(ICP.id))) or 0
    rows = db.scalars(
        select(ICP).order_by(ICP.created_at.desc()).limit(page.limit).offset(page.offset)
    )
    return Page.build([ICPOut.model_validate(r) for r in rows], total, page)


@router.get("/{icp_id}", response_model=ICPOut)
def get_icp(icp_id: UUID, db: DbSession, _: CurrentUser) -> ICP:
    icp = db.get(ICP, icp_id)
    if icp is None:
        raise NotFoundError(f"ICP {icp_id} does not exist")
    return icp
