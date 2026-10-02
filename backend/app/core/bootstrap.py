"""First-run setup.

Section 3.1 of the brief requires authenticated routes; Section 4 says to
assume a single user. Seeding one account from the environment satisfies both:
the API is genuinely protected, and nobody has to build or use a signup flow.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import hash_password
from app.models import User
from app.models.enums import UserRole

logger = get_logger(__name__)


def ensure_bootstrap_user(db: Session) -> User:
    """Seed the first administrator. Idempotent.

    Only ever creates; an existing account's role and password are left alone,
    so changing the environment variables cannot silently reset a live admin.
    """
    email = settings.bootstrap_user_email.lower()
    user = db.scalar(select(User).where(User.email == email))
    if user:
        return user

    user = User(
        email=email,
        hashed_password=hash_password(settings.bootstrap_user_password),
        full_name="Administrator",
        role=UserRole.ADMIN,
    )
    db.add(user)
    db.commit()
    logger.info("bootstrapped administrator %s", email)
    return user
