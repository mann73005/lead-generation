"""Shared building blocks for the ORM models."""

from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin

__all__ = ["Base", "TimestampMixin", "UUIDMixin", "enum_check"]


class UUIDMixin:
    """UUID primary key, generated application-side.

    Client-generated IDs let the discovery pipeline build a whole company +
    leads + score graph in memory and flush it in one transaction, without
    round-tripping to the database for each generated key.
    """

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)


def enum_check(column: str, enum_cls: type[StrEnum], *, name: str | None = None) -> CheckConstraint:
    """Constrain `column` to the members of `enum_cls` at the database level.

    The application already validates through Pydantic; this is the backstop
    for anything that writes to the database outside the API.
    """
    allowed = ", ".join(f"'{member.value}'" for member in enum_cls)
    return CheckConstraint(f"{column} IN ({allowed})", name=name or f"{column}_valid")
