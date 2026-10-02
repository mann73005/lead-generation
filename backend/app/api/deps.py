"""Shared FastAPI dependencies."""

from typing import Annotated

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import decode_token
from app.models import User
from app.schemas.common import PageParams

#: auto_error=False so a missing header surfaces through our own error
#: envelope instead of Starlette's default `{"detail": ...}` shape.
bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token")

DbSession = Annotated[Session, Depends(get_db)]
Pagination = Annotated[PageParams, Depends()]


def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    if credentials is None:
        raise UnauthorizedError("Missing bearer token")

    try:
        payload = decode_token(credentials.credentials, "access")
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("Access token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise UnauthorizedError("Invalid access token") from exc

    user = db.scalar(select(User).where(User.email == payload["sub"]))
    if user is None or not user.is_active:
        raise UnauthorizedError("User no longer exists or is inactive")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_admin(user: "CurrentUser") -> User:
    """Guard for account management.

    403 rather than 404: the caller is authenticated and the route exists, so
    pretending otherwise would only make the API harder to work with.
    """
    if not user.is_admin:
        raise ForbiddenError("This action requires an administrator account")
    return user


AdminUser = Annotated[User, Depends(require_admin)]
