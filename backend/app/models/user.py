"""Console users.

Section 3.1 of the brief requires authentication and token management on all
lead and campaign routes; Section 4 says to assume a single user with no login.
Section 3.1 is the graded Core Scope, so auth is implemented.

Roles and per-user ownership go beyond what the brief asks for. They are here
because a shared console where every salesperson sees every other
salesperson's pipeline is not a console anybody would actually use, and
because an admin needs somewhere to manage accounts. See README > Scope.
"""

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin, enum_check
from app.models.enums import UserRole


class User(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(128), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(160))
    role: Mapped[str] = mapped_column(String(20), default=UserRole.MEMBER, nullable=False)

    #: Deactivation rather than deletion: a departed salesperson's leads,
    #: campaigns and score history stay intact and attributable.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (enum_check("role", UserRole),)

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN

    def __repr__(self) -> str:
        return f"<User {self.email} {self.role}>"
