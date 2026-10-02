"""Authentication routes."""

import jwt
from fastapi import APIRouter, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.core.exceptions import UnauthorizedError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.models import User
from app.schemas.auth import LoginRequest, RefreshRequest, TokenPair, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


def _tokens(email: str) -> TokenPair:
    return TokenPair(
        access_token=create_access_token(email),
        refresh_token=create_refresh_token(email),
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post("/login", response_model=TokenPair)
def login(payload: LoginRequest, db: DbSession) -> TokenPair:
    user = db.scalar(select(User).where(User.email == payload.email.lower()))

    # Deliberately identical message for "no such user" and "wrong password",
    # so the endpoint cannot be used to enumerate accounts.
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise UnauthorizedError("Incorrect email or password")
    if not user.is_active:
        raise UnauthorizedError("Account is disabled")

    return _tokens(user.email)


@router.post("/refresh", response_model=TokenPair)
def refresh(payload: RefreshRequest, db: DbSession) -> TokenPair:
    try:
        claims = decode_token(payload.refresh_token, "refresh")
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("Refresh token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise UnauthorizedError("Invalid refresh token") from exc

    # Re-checked against the database: a token for a deleted or disabled user
    # must stop working immediately, not at its natural expiry.
    user = db.scalar(select(User).where(User.email == claims["sub"]))
    if user is None or not user.is_active:
        raise UnauthorizedError("User no longer exists or is inactive")

    return _tokens(user.email)


@router.get("/me", response_model=UserOut, status_code=status.HTTP_200_OK)
def me(user: CurrentUser) -> User:
    return user
