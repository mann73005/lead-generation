"""User administration.

Every route here is admin-only. Members have no account-management surface at
all, which is simpler to reason about than a partial one.
"""

from uuid import UUID

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import func, select

from app.api.deps import AdminUser, CurrentUser, DbSession, Pagination
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.security import hash_password
from app.models import User
from app.models.enums import UserRole
from app.schemas.common import Page

router = APIRouter(prefix="/users", tags=["users"])


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    full_name: str | None
    role: UserRole
    is_active: bool


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=160)
    role: UserRole = UserRole.MEMBER


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=160)
    role: UserRole | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)


@router.get("", response_model=Page[UserOut])
def list_users(db: DbSession, _: AdminUser, page: Pagination) -> Page[UserOut]:
    total = db.scalar(select(func.count(User.id))) or 0
    rows = db.scalars(
        select(User).order_by(User.created_at).limit(page.limit).offset(page.offset)
    )
    return Page.build([UserOut.model_validate(r) for r in rows], total, page)


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, db: DbSession, _: AdminUser) -> User:
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise ConflictError("A user with this email already exists")

    user = User(
        email=email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role=payload.role,
    )
    db.add(user)
    db.flush()
    return user


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: UUID, payload: UserUpdate, db: DbSession, admin: AdminUser
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError(f"User {user_id} does not exist")

    updates = payload.model_dump(exclude_unset=True)

    # An admin locking themselves out, or demoting themselves while they are
    # the only admin, leaves the console with no way back in.
    if user.id == admin.id:
        if updates.get("is_active") is False:
            raise ForbiddenError("You cannot deactivate your own account")
        if updates.get("role") == UserRole.MEMBER:
            raise ForbiddenError("You cannot remove your own administrator role")

    if updates.get("role") == UserRole.MEMBER and user.is_admin:
        remaining = db.scalar(
            select(func.count(User.id)).where(
                User.role == UserRole.ADMIN, User.is_active.is_(True), User.id != user.id
            )
        ) or 0
        if remaining == 0:
            raise ForbiddenError("At least one active administrator must remain")

    if (password := updates.pop("password", None)):
        user.hashed_password = hash_password(password)
    for field, value in updates.items():
        setattr(user, field, value)

    db.flush()
    return user


@router.get("/me/profile", response_model=UserOut)
def read_own_profile(user: CurrentUser) -> User:
    """The one user route a member can reach, for their own record."""
    return user
