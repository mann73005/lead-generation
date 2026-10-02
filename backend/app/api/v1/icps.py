"""ICP routes — the targeting criteria that drive discovery and fit scoring."""

from uuid import UUID

from fastapi import APIRouter, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, Pagination
from app.core.exceptions import NotFoundError
from app.models import ICP
from app.schemas.common import Page
from app.schemas.icp import ICPCreate, ICPOut, ICPUpdate

router = APIRouter(prefix="/icps", tags=["icps"])


def _owned(db, icp_id: UUID, user) -> ICP:
    """Fetch a profile the caller is allowed to touch.

    A member asking for someone else's profile gets the same answer as for
    one that does not exist: a 404 that distinguishes them is an existence
    oracle.
    """
    icp = db.get(ICP, icp_id)
    if icp is None or (not user.is_admin and icp.owner_id != user.id):
        raise NotFoundError(f"ICP {icp_id} does not exist")
    return icp


@router.post("", response_model=ICPOut, status_code=status.HTTP_201_CREATED)
def create_icp(payload: ICPCreate, db: DbSession, user: CurrentUser) -> ICP:
    icp = ICP(**payload.model_dump(), owner_id=user.id)
    db.add(icp)
    db.flush()
    return icp


@router.get("", response_model=Page[ICPOut])
def list_icps(db: DbSession, user: CurrentUser, page: Pagination) -> Page[ICPOut]:
    mine = [] if user.is_admin else [ICP.owner_id == user.id]
    total = db.scalar(select(func.count(ICP.id)).where(*mine)) or 0
    rows = db.scalars(
        select(ICP).where(*mine).order_by(ICP.created_at.desc()).limit(page.limit).offset(page.offset)
    )
    return Page.build([ICPOut.model_validate(r) for r in rows], total, page)


@router.patch("/{icp_id}", response_model=ICPOut)
def update_icp(icp_id: UUID, payload: ICPUpdate, db: DbSession, user: CurrentUser) -> ICP:
    """Edit a profile.

    Existing leads are not rescored here. Their scores are recomputed on their
    next event, or immediately via POST /leads/{id}/rescore — doing it silently
    for a whole list as a side effect of an edit would be a surprising amount
    of work to trigger from a text field.
    """
    icp = _owned(db, icp_id, user)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(icp, field, value)
    db.flush()
    return icp


@router.get("/{icp_id}", response_model=ICPOut)
def get_icp(icp_id: UUID, db: DbSession, user: CurrentUser) -> ICP:
    return _owned(db, icp_id, user)
