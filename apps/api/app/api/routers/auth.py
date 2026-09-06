"""Authentication endpoints (docs/api.md §4).

The routers are thin on purpose: they validate a body, call one service method,
and translate the result into a response and — uniquely for this router —
cookies. Cookie writing lives here because it is the one part of authentication
that is genuinely HTTP; everything else is in `app.services.authentication` and
`app.auth`, where the CLI and the tests can reach it.
"""

from __future__ import annotations

from typing import Any, Final

from fastapi import APIRouter, Response, status

from app.api.cookies import clear_session_cookies, set_session_cookies
from app.api.dependencies import AppSettings, AuthService, RequestOriginDep, SessionScope
from app.schemas.auth import CurrentUserResponse, LoginRequest, PasswordChangeRequest
from app.schemas.errors import ErrorEnvelope

router = APIRouter(prefix="/auth", tags=["authentication"])

#: OpenAPI response documentation. Typed so it can be merged into a route's
#: `responses` without mypy inferring `dict[str, object]`.
_Responses = dict[int | str, dict[str, Any]]

_UNIFORM_LOGIN_FAILURE: Final[_Responses] = {
    401: {
        "model": ErrorEnvelope,
        "description": (
            "AUTH_INVALID_CREDENTIALS. The same response for an unknown address, a "
            "wrong password, a locked identity and a deactivated account."
        ),
    },
    429: {"model": ErrorEnvelope, "description": "TOO_MANY_REQUESTS — login throttled."},
}

_AUTHENTICATED: Final[_Responses] = {
    401: {"model": ErrorEnvelope, "description": "No usable session."},
    403: {"model": ErrorEnvelope, "description": "CSRF_TOKEN_INVALID."},
}


@router.post(
    "/login",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Log in",
    responses=_UNIFORM_LOGIN_FAILURE,
)
async def login(
    body: LoginRequest,
    response: Response,
    service: AuthService,
    origin: RequestOriginDep,
    settings: AppSettings,
) -> None:
    """Authenticate and issue a session.

    No body: everything the client needs is in the two cookies, and returning
    the user here would duplicate `GET /auth/me` and invite it to be cached.
    """
    issued = await service.login(email=body.email, password=body.password, origin=origin)
    set_session_cookies(response, issued, settings)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Log out",
    responses=_AUTHENTICATED,
)
async def logout(
    response: Response,
    scope: SessionScope,
    service: AuthService,
    origin: RequestOriginDep,
    settings: AppSettings,
) -> None:
    """Revoke the current session and clear its cookies.

    Usable with an unrotated temporary password: an account must always be able
    to sign out of itself.
    """
    await service.logout(scope, origin=origin)
    clear_session_cookies(response, settings)


@router.get(
    "/me",
    summary="The authenticated user",
    responses={401: {"model": ErrorEnvelope, "description": "No usable session."}},
)
async def me(scope: SessionScope) -> CurrentUserResponse:
    """Who the caller is, and whether they must change their password first.

    Deliberately exempt from the `must_change_password` gate: the web app calls
    this before it can know it needs to send the user to the rotation form.
    """
    actor = scope.actor
    return CurrentUserResponse(
        id=actor.id,
        email=actor.email,
        full_name=actor.full_name,
        role=actor.role,
        must_change_password=actor.must_change_password,
    )


@router.post(
    "/password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Change your own password",
    responses={
        **_AUTHENTICATED,
        422: {
            "model": ErrorEnvelope,
            "description": (
                "CURRENT_PASSWORD_INVALID, or PASSWORD_INVALID with one details "
                "entry per policy violation."
            ),
        },
    },
)
async def change_password(
    body: PasswordChangeRequest,
    response: Response,
    scope: SessionScope,
    service: AuthService,
    origin: RequestOriginDep,
    settings: AppSettings,
) -> None:
    """Rotate the caller's password, then re-issue their session.

    The full sequence, in one transaction: verify `current_password`, apply the
    password policy, replace the Argon2id hash, clear `must_change_password`,
    reset any lockout counters, revoke **every** existing session of the user,
    and issue a fresh one. The new session and CSRF cookies are on this
    response, so the caller stays signed in while every other device is signed
    out — which is what makes this the right response to a suspected
    compromise.
    """
    issued = await service.change_own_password(
        scope,
        current_password=body.current_password,
        new_password=body.new_password,
        origin=origin,
    )
    set_session_cookies(response, issued, settings)
