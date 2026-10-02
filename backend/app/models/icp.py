"""Ideal Customer Profile definitions and the discovery runs they drive."""

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin, enum_check
from app.models.enums import DiscoveryRunStatus

if TYPE_CHECKING:
    from app.models.lead import Lead


class ICP(UUIDMixin, TimestampMixin, Base):
    """The salesperson's targeting criteria. Also the input to lead scoring."""

    __tablename__ = "icps"

    #: Who defined this profile. Members see only their own; admins see all.
    owner_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    industry: Mapped[str] = mapped_column(String(120), nullable=False)
    region: Mapped[str] = mapped_column(String(120), nullable=False)
    employee_min: Mapped[int | None] = mapped_column()
    employee_max: Mapped[int | None] = mapped_column()

    #: Target job titles, e.g. ["Head of Merchandising", "Demand Planning"].
    titles: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    keywords: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)

    runs: Mapped[list["DiscoveryRun"]] = relationship(
        back_populates="icp", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        CheckConstraint(
            "employee_min IS NULL OR employee_max IS NULL OR employee_min <= employee_max",
            name="employee_range_ordered",
        ),
        CheckConstraint("employee_min IS NULL OR employee_min >= 0", name="employee_min_non_negative"),
    )

    def __repr__(self) -> str:
        return f"<ICP {self.name!r}>"


class DiscoveryRun(UUIDMixin, TimestampMixin, Base):
    """One execution of the search-then-extract discovery flow.

    `agent_log` holds the full tool-call transcript so a run can be audited
    after the fact: which queries the model issued, what came back, and which
    candidates survived validation.
    """

    __tablename__ = "discovery_runs"

    icp_id: Mapped[UUID] = mapped_column(
        ForeignKey("icps.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), default=DiscoveryRunStatus.RUNNING, nullable=False
    )
    requested_count: Mapped[int] = mapped_column(default=8, nullable=False)
    companies_created: Mapped[int] = mapped_column(default=0, nullable=False)
    leads_created: Mapped[int] = mapped_column(default=0, nullable=False)
    leads_rejected: Mapped[int] = mapped_column(default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    agent_log: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    icp: Mapped["ICP"] = relationship(back_populates="runs")
    leads: Mapped[list["Lead"]] = relationship(back_populates="discovery_run")

    __table_args__ = (
        enum_check("status", DiscoveryRunStatus),
        CheckConstraint("requested_count BETWEEN 1 AND 50", name="requested_count_in_range"),
    )

    def __repr__(self) -> str:
        return f"<DiscoveryRun {self.id} {self.status}>"
