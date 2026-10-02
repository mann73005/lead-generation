"""Company routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.api.deps import CurrentUser, DbSession, Pagination
from app.core.exceptions import ConflictError, NotFoundError
from app.models import Company
from app.schemas.common import Page
from app.schemas.lead import CompanyOut

router = APIRouter(prefix="/companies", tags=["companies"])


class CompanyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    domain: str | None = Field(default=None, max_length=255)
    industry: str | None = Field(default=None, max_length=120)
    region: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, max_length=120)
    employee_count: int | None = Field(default=None, ge=0)
    description: str | None = None
    source_url: str = Field(min_length=8, description="Page these facts came from.")


@router.post("", response_model=CompanyOut, status_code=status.HTTP_201_CREATED)
def create_company(payload: CompanyCreate, db: DbSession, _: CurrentUser) -> Company:
    if payload.domain:
        existing = db.scalar(select(Company).where(Company.domain == payload.domain))
        if existing:
            raise ConflictError(
                "A company with this domain already exists",
                details={"existing_company_id": str(existing.id)},
            )

    company = Company(**payload.model_dump())
    db.add(company)
    db.flush()
    return company


@router.get("", response_model=Page[CompanyOut])
def list_companies(
    db: DbSession,
    _: CurrentUser,
    page: Pagination,
    q: Annotated[str | None, Query(max_length=120)] = None,
    industry: Annotated[str | None, Query(max_length=120)] = None,
) -> Page[CompanyOut]:
    stmt = select(Company)
    count_stmt = select(func.count(Company.id))

    if q:
        term = f"%{q.strip()}%"
        condition = or_(Company.name.ilike(term), Company.domain.ilike(term))
        stmt, count_stmt = stmt.where(condition), count_stmt.where(condition)
    if industry:
        condition = Company.industry.ilike(f"%{industry}%")
        stmt, count_stmt = stmt.where(condition), count_stmt.where(condition)

    total = db.scalar(count_stmt) or 0
    rows = db.scalars(stmt.order_by(Company.name).limit(page.limit).offset(page.offset))
    return Page.build([CompanyOut.model_validate(r) for r in rows], total, page)


@router.get("/{company_id}", response_model=CompanyOut)
def get_company(company_id: UUID, db: DbSession, _: CurrentUser) -> Company:
    company = db.get(Company, company_id)
    if company is None:
        raise NotFoundError(f"Company {company_id} does not exist")
    return company
