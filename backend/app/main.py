"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.tracking import router as tracking_router
from app.api.v1 import api_router
from app.core.bootstrap import ensure_bootstrap_user
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.services.product_profile import ensure_product_profile

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    with SessionLocal() as db:
        ensure_bootstrap_user(db)
        # Seeded from config/product.yaml on first boot only; after that the
        # row is owned by the console and edits are never overwritten.
        ensure_product_profile(db)

    logger.info(
        "providers — llm:%s search:%s email:%s",
        settings.llm_enabled,
        settings.search_enabled,
        settings.email_enabled,
    )
    yield


app = FastAPI(
    title="StyleSense AI — Lead Generation API",
    version="1.0.0",
    description=(
        "Lead discovery, scoring, outreach and engagement tracking.\n\n"
        "All routes except `/health`, `/t/*` (tracking pixel) and `/u/*` "
        "(unsubscribe) require a bearer token from `POST /api/v1/auth/login`."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)
app.include_router(api_router)
# Mounted at the root, outside /api/v1: these URLs are embedded in emails and
# need to stay short and stable across API versions.
app.include_router(tracking_router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, object]:
    """Liveness probe. Unauthenticated by design."""
    return {
        "status": "ok",
        "environment": settings.environment,
        "providers": {
            "llm": settings.llm_enabled,
            "search": settings.search_enabled,
            "email": settings.email_enabled,
        },
    }
