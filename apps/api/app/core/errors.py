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

    Codes are added by the phase that can actually raise them, each with a
    matching entry in the web message catalog. Phase 1 defined the
    infrastructure level; Phase 2 added authentication, authorization and user
    administration. Feature codes (`CASE_INVALID_STATUS_TRANSITION`, …) arrive
    with their features.
    """

    # Infrastructure (Phase 1)
    BAD_REQUEST = "BAD_REQUEST"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    CONFLICT = "CONFLICT"
    TOO_MANY_REQUESTS = "TOO_MANY_REQUESTS"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"

    # Authentication and sessions (Phase 2)
    AUTH_REQUIRED = "AUTH_REQUIRED"
    #: The single public answer to every login failure, whatever the cause
    #: (docs/security.md §2). Never split into "no such email" and "wrong
    #: password": that pair is a user-enumeration oracle.
    AUTH_INVALID_CREDENTIALS = "AUTH_INVALID_CREDENTIALS"
    AUTH_SESSION_EXPIRED = "AUTH_SESSION_EXPIRED"
    AUTH_ACCOUNT_INACTIVE = "AUTH_ACCOUNT_INACTIVE"
    CSRF_TOKEN_INVALID = "CSRF_TOKEN_INVALID"  # noqa: S105 - an error code, not a secret

    # Passwords (Phase 2)
    PASSWORD_CHANGE_REQUIRED = "PASSWORD_CHANGE_REQUIRED"  # noqa: S105 - an error code, not a secret
    PASSWORD_INVALID = "PASSWORD_INVALID"  # noqa: S105 - an error code, not a secret
    CURRENT_PASSWORD_INVALID = "CURRENT_PASSWORD_INVALID"  # noqa: S105 - an error code, not a secret

    # Authorization and user administration (Phase 2)
    FORBIDDEN = "FORBIDDEN"
    USER_NOT_FOUND = "USER_NOT_FOUND"
    USER_EMAIL_CONFLICT = "USER_EMAIL_CONFLICT"
    #: Guards against making the system unadministrable. There is no
    #: self-service password reset and no default account in Release 1
    #: (ADR-0026), so an organisation with no active admin cannot recover
    #: through the API at all — only by running the bootstrap CLI against the
    #: database again.
    USER_SELF_DEACTIVATION = "USER_SELF_DEACTIVATION"
    USER_LAST_ADMIN = "USER_LAST_ADMIN"

    # People (Phase 4)
    PERSON_NOT_FOUND = "PERSON_NOT_FOUND"
    PERSON_ACCESS_DENIED = "PERSON_ACCESS_DENIED"
    PERSON_IDENTIFIER_CONFLICT = "PERSON_IDENTIFIER_CONFLICT"
    PERSON_ALREADY_ARCHIVED = "PERSON_ALREADY_ARCHIVED"
    PERSON_NOT_ARCHIVED = "PERSON_NOT_ARCHIVED"


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


class TooManyRequestsError(AppError):
    """A caller has exceeded a rate limit. Used by login throttling."""

    code = ErrorCode.TOO_MANY_REQUESTS
    status_code = 429
    message = "Too many requests. Try again later."


class ServiceUnavailableError(AppError):
    """A dependency the request needs is not available.

    The message is deliberately uninformative: readiness failures must not
    disclose hostnames, credentials, driver text or topology (docs/security.md §5).
    """

    code = ErrorCode.SERVICE_UNAVAILABLE
    status_code = 503
    message = "The service is temporarily unavailable."


# ---------------------------------------------------------------------------
# Authentication and sessions
# ---------------------------------------------------------------------------


class AuthenticationRequiredError(AppError):
    """No usable session accompanied the request."""

    code = ErrorCode.AUTH_REQUIRED
    status_code = 401
    message = "Authentication is required."


class InvalidCredentialsError(AppError):
    """The one answer every login failure gets.

    Unknown email, wrong password, locked identity and deactivated account all
    raise *this*, with this message, so the endpoint cannot be used to discover
    which accounts exist (docs/security.md §2). The real reason is recorded in
    the audit trail and the server log, where only staff can read it.
    """

    code = ErrorCode.AUTH_INVALID_CREDENTIALS
    status_code = 401
    message = "Those credentials are not valid."


class SessionExpiredError(AppError):
    """The session existed but has passed its idle or absolute expiry."""

    code = ErrorCode.AUTH_SESSION_EXPIRED
    status_code = 401
    message = "The session has expired."


class AccountInactiveError(AppError):
    """The session's user has been deactivated since the session was issued.

    Distinct from `InvalidCredentialsError` on purpose: this is answered to
    somebody who already held a valid session, so it discloses nothing they did
    not already know, and "your account was disabled" is the only honest thing
    to tell them.
    """

    code = ErrorCode.AUTH_ACCOUNT_INACTIVE
    status_code = 401
    message = "This account is not active."


class CsrfTokenInvalidError(AppError):
    """The `X-CSRF-Token` header was missing, malformed, or bound to another session."""

    code = ErrorCode.CSRF_TOKEN_INVALID
    status_code = 403
    message = "The CSRF token is missing or invalid."


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------


class PasswordChangeRequiredError(AppError):
    """An authenticated user still holds a temporary password (ADR-0026).

    Everything except reading the current identity, rotating the password and
    logging out is refused until it is changed.
    """

    code = ErrorCode.PASSWORD_CHANGE_REQUIRED
    status_code = 403
    message = "The password must be changed before this endpoint can be used."


class PasswordInvalidError(AppError):
    """The proposed new password fails the policy in `app.domain.passwords`.

    `details` carries the stable policy codes; it never carries the password.
    """

    code = ErrorCode.PASSWORD_INVALID
    status_code = 422
    message = "The password does not meet the password policy."


class CurrentPasswordInvalidError(AppError):
    """The `current_password` supplied to a self-service password change is wrong.

    Not a user-enumeration concern: the caller is already authenticated as the
    account in question.
    """

    code = ErrorCode.CURRENT_PASSWORD_INVALID
    status_code = 422
    message = "The current password is not correct."


# ---------------------------------------------------------------------------
# Authorization and user administration
# ---------------------------------------------------------------------------


class ForbiddenError(AppError):
    """Authenticated, resource visible, action not permitted for this role.

    `404` is the answer when the resource is outside the actor's visibility
    scope; this is the "visible but not permitted" case (ADR-0021).
    """

    code = ErrorCode.FORBIDDEN
    status_code = 403
    message = "This action is not permitted for your role."


class UserNotFoundError(NotFoundError):
    code = ErrorCode.USER_NOT_FOUND
    message = "That user does not exist."


class UserEmailConflictError(ConflictError):
    code = ErrorCode.USER_EMAIL_CONFLICT
    message = "A user with that email address already exists."


class SelfDeactivationError(ConflictError):
    """An admin tried to deactivate their own account.

    Refused because it would end the caller's own session mid-request and,
    if they were the only admin, leave nobody able to undo it.
    """

    code = ErrorCode.USER_SELF_DEACTIVATION
    message = "An account cannot deactivate itself."


class LastAdminError(ConflictError):
    """The last active admin cannot be demoted or deactivated.

    With no self-service password reset and no default account (ADR-0026), an
    organisation with zero active admins can only be recovered by running the
    bootstrap CLI with database access.
    """

    code = ErrorCode.USER_LAST_ADMIN
    message = "The last active administrator cannot be demoted or deactivated."


# ---------------------------------------------------------------------------
# People
# ---------------------------------------------------------------------------


class PersonNotFoundError(NotFoundError):
    code = ErrorCode.PERSON_NOT_FOUND
    message = "That person does not exist."


class PersonAccessDeniedError(AppError):
    """The caller can see that the person exists but may not edit them (ADR-0027).

    Search already disclosed existence, so this is `403`, not `404`.
    """

    code = ErrorCode.PERSON_ACCESS_DENIED
    status_code = 403
    message = "You do not have access to edit this person."


class PersonIdentifierConflictError(ConflictError):
    code = ErrorCode.PERSON_IDENTIFIER_CONFLICT
    message = "A person with that identifier already exists."


class PersonAlreadyArchivedError(ConflictError):
    code = ErrorCode.PERSON_ALREADY_ARCHIVED
    message = "That person is already archived."


class PersonNotArchivedError(ConflictError):
    code = ErrorCode.PERSON_NOT_ARCHIVED
    message = "That person is not archived."
