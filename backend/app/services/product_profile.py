"""Access to the seller's profile.

`config/product.yaml` is the seed, not the source of truth. Once the row
exists the database owns it, so the console can change the pitch, the sender or
the template without a redeploy.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.core.policy import ProductConfig, load_product_config
from app.models import ProductProfile

logger = get_logger(__name__)


def ensure_product_profile(db: Session) -> ProductProfile:
    """Seed the active profile from YAML on first boot. Idempotent."""
    existing = db.scalar(select(ProductProfile).where(ProductProfile.is_active.is_(True)))
    if existing:
        return existing

    seed = load_product_config()
    profile = ProductProfile(
        name=seed.identity.name,
        description=seed.identity.description,
        sender_name=seed.identity.name,
        sender_email="",
        segments=seed.identity.segments,
        pain_points={k: v.model_dump() for k, v in seed.pain_points.items()},
        research_signals=seed.research_signals,
        template=seed.template.model_dump(),
        is_active=True,
    )
    db.add(profile)
    db.commit()
    logger.info("seeded product profile %r from config/product.yaml", profile.name)
    return profile


def get_active_profile(db: Session) -> ProductProfile:
    profile = db.scalar(select(ProductProfile).where(ProductProfile.is_active.is_(True)))
    if profile is None:
        raise NotFoundError("No active product profile is configured")
    return profile


def to_config(profile: ProductProfile) -> ProductConfig:
    """Validate a stored row back into the same shape the YAML produces.

    Running the database row through the identical schema means a profile
    edited badly through the API fails the same validation as a badly edited
    config file — rather than surfacing as a broken email.
    """
    return ProductConfig.model_validate(
        {
            "version": 1,
            "identity": {
                "name": profile.name,
                "description": profile.description,
                "segments": profile.segments or {"default": "retail"},
            },
            "pain_points": profile.pain_points or {},
            "research_signals": profile.research_signals or [],
            "template": profile.template,
        }
    )
