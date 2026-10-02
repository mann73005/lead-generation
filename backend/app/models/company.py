"""Companies — the organisations leads belong to."""

from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.lead import Lead


class Company(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(255))
    industry: Mapped[str | None] = mapped_column(String(120))
    region: Mapped[str | None] = mapped_column(String(120))
    country: Mapped[str | None] = mapped_column(String(120))
    employee_count: Mapped[int | None] = mapped_column()
    description: Mapped[str | None] = mapped_column(Text)

    #: Where this company's facts came from. Required: the grounding check
    #: refuses to fill a token from a field with no citable origin.
    source_url: Mapped[str] = mapped_column(Text, nullable=False)

    #: Verbatim provider payload (search snippets, fetched page extracts).
    #: Kept so a token's value can be traced back to the text that produced it.
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    leads: Mapped[list["Lead"]] = relationship(
        back_populates="company", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        # NULL domains do not collide in PostgreSQL, so companies discovered
        # without a resolvable website can still coexist.
        UniqueConstraint("domain", name="uq_companies_domain"),
        CheckConstraint("employee_count IS NULL OR employee_count >= 0", name="employee_count_non_negative"),
        Index("ix_companies_industry_region", "industry", "region"),
    )

    def __repr__(self) -> str:
        return f"<Company {self.name!r}>"
