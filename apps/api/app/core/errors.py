"""The application error model.

Every non-2xx response the API produces is the envelope documented in
`docs/api.md` §2:

    {"error": {"code", "message", "details", "request_id"}}

`AppError` is what application and domain code raises; `app.api.exception_handlers`
is the only place that turns one into HTTP. Keeping the exception classes free of
FastAPI means services and domain logic can raise them without importing a web
framework, and unit tests can assert on them without an HTTP client.

Messages are English and developer-facing (ADR-0014); the Hebrew a user reads is
selected in the web application from `code`. Nothing here ever carries a stack
trace, SQL, a driver message or a configuration value.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ErrorCode(StrEnum):
    """Stable, machine-readable error codes.

    Phase 1 defines the infrastructure-level codes only. Business codes
    (`AUTH_INVALID_CREDENTIALS`, `CASE_INVALID_STATUS_TRANSITION`, …) are added
    by the phases that can actually raise them, each with a matching entry in
    the web message catalog.
    """

    BAD_REQUEST = "BAD_REQUEST"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    CONFLICT = "CONFLICT"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class ErrorDetail:
    """One field-level problem. `field` is `None` for whole-request problems."""

    issue: str
    field: str | None = None


class AppError(Exception):
    """Base class for every error the application raises deliberately.

    Subclasses set `code` and `status_code`; the message is developer-facing and
    is returned to the caller, so it must never be built from an internal
    exception, a query, or a configuration value.
    """

    code: ErrorCode = ErrorCode.INTERNAL_ERROR
    status_code: int = 500
    message: str = "The request could not be completed."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: list[ErrorDetail] | None = None,
    ) -> None:
        self.message = message or type(self).message
        self.details: list[ErrorDetail] = details or []
        super().__init__(self.message)


class BadRequestError(AppError):
    code = ErrorCode.BAD_REQUEST
    status_code = 400
    message = "The request was malformed."


class ValidationFailedError(AppError):
    """A semantic validation failure raised by the application.

    Field-level failures detected by Pydantic at the HTTP boundary produce the
    same envelope through the framework's own handler; this is for the rules
    that only a service can check.
    """

    code = ErrorCode.VALIDATION_ERROR
    status_code = 422
    message = "The request failed validation."


class NotFoundError(AppError):
    code = ErrorCode.NOT_FOUND
    status_code = 404
    message = "The requested resource does not exist."


class ConflictError(AppError):
    code = ErrorCode.CONFLICT
    status_code = 409
    message = "The request conflicts with the current state of the resource."


class ServiceUnavailableError(AppError):
    """A dependency the request needs is not available.

    The message is deliberately uninformative: readiness failures must not
    disclose hostnames, credentials, driver text or topology (docs/security.md §5).
    """

    code = ErrorCode.SERVICE_UNAVAILABLE
    status_code = 503
    message = "The service is temporarily unavailable."
