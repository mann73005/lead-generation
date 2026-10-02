"""The seller's own profile: who is writing, what they sell, and the template.

This is deliberately a table rather than a config file. `config/product.yaml`
seeds it on first boot and is the default, but once the row exists the console
owns it: a salesperson changes the pitch, the pain-point mapping or the sender
name through the API and the next generated email uses it immediately. A
redeploy to change a subject line is not a workflow anybody wants.
"""

from typing import Any

from sqlalchemy import Boolean, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class ProductProfile(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "product_profiles"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    sender_name: Mapped[str] = mapped_column(String(120), nullable=False)
    sender_email: Mapped[str] = mapped_column(String(320), nullable=False)

    #: {{company_segment}} resolution: a default plus keyword overrides.
    segments: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    #: pain point key -> {label, capability, signals[]}.
    pain_points: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    #: Groups of keywords worth treating as a personalisation hook.
    research_signals: Mapped[list[Any]] = mapped_column(JSONB, default=list, nullable=False)
    #: The locked skeleton: subject options, ordered sentences, optional tokens.
    template: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (
        # At most one active profile, enforced by the database rather than by
        # whichever code path happened to write last.
        Index(
            "uq_product_profiles_single_active",
            "is_active",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    def __repr__(self) -> str:
        return f"<ProductProfile {self.name!r} active={self.is_active}>"
