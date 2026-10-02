"""Product profile routes.

Lets the console own the pitch: who is sending, what is being sold, which pain
points map to which capability, and the outreach skeleton itself. Edits take
effect on the next generated email, with no redeploy.
"""

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.core.exceptions import BadRequestError
from app.models import ProductProfile
from app.schemas.product import ProductProfileOut, ProductProfileUpdate
from app.services.product_profile import get_active_profile, to_config

router = APIRouter(prefix="/product-profile", tags=["product"])


@router.get("", response_model=ProductProfileOut)
def read_profile(db: DbSession, _: CurrentUser) -> ProductProfile:
    return get_active_profile(db)


@router.patch("", response_model=ProductProfileOut)
def update_profile(
    payload: ProductProfileUpdate, db: DbSession, _: CurrentUser
) -> ProductProfile:
    profile = get_active_profile(db)

    for field, value in payload.as_columns().items():
        setattr(profile, field, value)
    db.flush()

    # Re-validated as a whole before the change is allowed to stand. A template
    # that passes field validation can still be internally inconsistent — a
    # sentence requiring a token it no longer contains, say — and that would
    # otherwise only surface when a salesperson tried to mail someone.
    try:
        to_config(profile)
    except ValueError as exc:
        db.rollback()
        raise BadRequestError(
            "The updated profile is not internally consistent",
            details={"error": str(exc)[:400]},
        ) from exc

    return profile
