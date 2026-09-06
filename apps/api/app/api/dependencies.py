"""FastAPI dependencies shared by routers.

This module is the authentication and authorization boundary for the HTTP
layer. Routers declare what they need through the annotated aliases at the
bottom and never reach for a cookie, a header or a role check themselves.

The chain, and the reason it is a chain rather than three independent
dependencies:

    SessionScope   resolve the cookie → a live session, then verify CSRF
        ↓
    CurrentActor   + the temporary-password gate
        ↓
    AdminActor / StaffActor   + the role gate

Each layer builds on the one above, so **the safe behaviour is the default and
an omission removes protection visibly rather than silently**. An endpoint that
asks for `CurrentActor` cannot forget CSRF, because there is no way to obtain an
actor without passing through it. The three endpoints that must work while a
temporary password is outstanding opt out by asking for `SessionScope`, which is
a visible, greppable exception rather than a missing line.

`app.api` may not import `app.models` (docs/architecture.md §4), so nothing here
handles an ORM object: session resolution returns a `SessionContext` carrying an
`AuthenticatedActor`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, Final

import structlog
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.api.cookies import read_csrf_header, read_session_token
from app.auth.policies import ensure_password_rotated, ensure_role
from app.auth.sessions import SessionContext
from app.core.errors import AuthenticationRequiredError, CsrfTokenInvalidError
from app.core.settings import Settings, get_settings
from app.db.session import get_db_session
from app.domain.actor import AuthenticatedActor
from app.domain.enums import UserRole
from app.services.authentication import AuthenticationService, RequestOrigin

DbSession = Annotated[AsyncSession, Depends(get_db_session)]

#: CSRF applies to state-changing methods only (docs/security.md §3). `GET`,
#: `HEAD` and `OPTIONS` are exempt because a forged one changes nothing, and
#: requiring a token on them would break the preflight and the browser's own
#: navigation.
SAFE_METHODS: Final = frozenset({"GET", "HEAD", "OPTIONS"})


def get_app_settings() -> Settings:
    """The process settings, as a dependency so a test can override them."""
    return get_settings()


AppSettings = Annotated[Settings, Depends(get_app_settings)]


def get_request_origin(request: Request) -> RequestOrigin:
    """Where the request came from, for audit rows and login throttling.

    The address is the peer as the ASGI server reports it. Behind the
    same-origin Next.js proxy that is the proxy unless the server is run with
    `--proxy-headers` and a trusted forwarded-for allowlist, which is a
    deployment setting; the consequence for throttling is documented in
    `app.auth.throttle` and in `docs/security.md`.
    """
    return RequestOrigin(
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


RequestOriginDep = Annotated[RequestOrigin, Depends(get_request_origin)]


def get_authentication_service(session: DbSession, settings: AppSettings) -> AuthenticationService:
    return AuthenticationService(session, settings)


AuthService = Annotated[AuthenticationService, Depends(get_authentication_service)]


async def get_session_scope(
    request: Request,
    service: AuthService,
    origin: RequestOriginDep,
) -> SessionContext:
    """Resolve the session cookie and verify CSRF on unsafe methods.

    Raises `AUTH_REQUIRED` when there is no cookie, `AUTH_SESSION_EXPIRED` when
    the session is revoked or past either expiry, `AUTH_ACCOUNT_INACTIVE` when
    the user has been deactivated, and `CSRF_TOKEN_INVALID` when a
    state-changing request does not carry the token bound to this session.
    """
    token = read_session_token(request)
    if token is None:
        raise AuthenticationRequiredError

    context = await service.resolve_session(token)
    # The access log line for this request now carries who made it
    # (docs/architecture.md §10). Bound rather than passed, so no service or
    # logger needs a `Request`.
    structlog.contextvars.bind_contextvars(user_id=str(context.actor.id))

    if request.method not in SAFE_METHODS:
        submitted = read_csrf_header(request)
        if submitted is None or not context.csrf_token_matches(submitted):
            # Recorded in its own transaction, because this request is about to
            # fail and the request-scoped session is rolled back on the way out
            # (docs/security.md §3).
            await service.record_csrf_failure(context, origin=origin)
            raise CsrfTokenInvalidError

    return context


#: Authenticated and CSRF-verified, *without* the temporary-password gate. Only
#: the three endpoints an account needs in order to rotate a temporary password
#: use this: `GET /auth/me`, `POST /auth/password` and `POST /auth/logout`.
SessionScope = Annotated[SessionContext, Depends(get_session_scope)]


async def get_current_actor(context: SessionScope) -> AuthenticatedActor:
    """The caller, for an ordinary application endpoint.

    Adds the forced-rotation gate of ADR-0026 to `SessionScope`: while
    `must_change_password` is set, this raises `PASSWORD_CHANGE_REQUIRED`.
    """
    ensure_password_rotated(context.actor)
    return context.actor


CurrentActor = Annotated[AuthenticatedActor, Depends(get_current_actor)]


def require_role(
    *allowed: UserRole,
) -> Callable[[AuthenticatedActor], Awaitable[AuthenticatedActor]]:
    """A dependency that admits only the listed roles (docs/security.md §4).

    The service the router calls re-checks the same rule, so a router wired
    without one of these still cannot perform an admin action
    (docs/architecture.md §6).
    """

    async def dependency(actor: CurrentActor) -> AuthenticatedActor:
        ensure_role(actor, *allowed)
        return actor

    return dependency


AdminActor = Annotated[AuthenticatedActor, Depends(require_role(UserRole.ADMIN))]
StaffActor = Annotated[AuthenticatedActor, Depends(require_role(UserRole.ADMIN, UserRole.EMPLOYEE))]
