"""Application errors and the handlers that render them.

Every failure leaving the API has the same shape, so the console has exactly
one error branch to write:

    {"error": {"code": "lead_not_found", "message": "...", "details": {...}}}
"""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger

logger = get_logger(__name__)


class AppError(Exception):
    """Base class for errors that map onto a deliberate HTTP response."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"


class BadRequestError(AppError):
    status_code = 400
    code = "bad_request"


class ForbiddenError(AppError):
    """Authenticated, but not allowed to do this."""

    status_code = 403
    code = "forbidden"


class SuppressedRecipientError(ConflictError):
    """Attempted send to an address on the suppression list."""

    code = "recipient_suppressed"


class ProviderError(AppError):
    """An upstream provider (LLM, search, email) failed.

    502 rather than 500: the fault is outside this service, and the console
    shows a retry affordance for these specifically.
    """

    status_code = 502
    code = "provider_error"


class ProviderUnavailableError(ProviderError):
    """Provider is configured but temporarily refusing work (429/503)."""

    status_code = 503
    code = "provider_unavailable"


class RateLimitedError(ProviderUnavailableError):
    """Quota exhausted. Distinct from an outage because the remedy is to wait,
    not to retry against a different model."""

    code = "rate_limited"


class ProviderNotConfiguredError(ProviderError):
    """A required API key is absent, so the feature cannot run at all."""

    status_code = 503
    code = "provider_not_configured"


class GroundingError(AppError):
    """Email generation produced nothing that survives the grounding check."""

    status_code = 422
    code = "grounding_failed"


def _payload(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        if exc.status_code >= 500:
            logger.error("%s: %s", exc.code, exc.message, extra={"details": exc.details})
        return JSONResponse(status_code=exc.status_code, content=_payload(exc.code, exc.message, exc.details))

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Re-shaped into our envelope so clients never see two error formats.
        fields = [
            {
                "field": ".".join(str(p) for p in err["loc"][1:]) or str(err["loc"][0]),
                "message": err["msg"],
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=422, content=_payload("validation_error", "Request validation failed", {"fields": fields})
        )

    @app.exception_handler(IntegrityError)
    async def _integrity(_: Request, exc: IntegrityError) -> JSONResponse:
        """A constraint the application did not check first.

        The database message is deliberately not forwarded: it leaks column and
        constraint names. The constraint name is logged instead.
        """
        logger.warning("integrity error: %s", exc.orig)
        return JSONResponse(
            status_code=409,
            content=_payload(
                "constraint_violation",
                "The request conflicts with existing data.",
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_payload(f"http_{exc.status_code}", str(exc.detail)),
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error", exc_info=exc)
        return JSONResponse(
            status_code=500, content=_payload("internal_error", "An unexpected error occurred.")
        )
