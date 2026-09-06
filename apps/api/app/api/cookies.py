"""The session and CSRF cookies (docs/security.md §3, ADR-0005).

One module writes these headers, so the attribute policy is stated once and
tested once instead of being repeated at three call sites and drifting.

* `HttpOnly` — set on the session cookie, and deliberately **not** on the CSRF
  cookie: the session token must be unreadable from JavaScript, while the CSRF
  token has to be readable, because the client's whole job is to echo it back
  in a header.
* `Secure` — on both, in production. Relaxed only for plain-HTTP local
  development, and a production process refuses to start with it disabled.
* `SameSite=Lax` — on both; see below.
* `Path=/` — one session for the whole application.
* No `Domain` — omitting the attribute produces a host-only cookie. Setting it
  would share the cookie with every subdomain.
* No expiry — both are session cookies, so they go when the browser does. The
  server-side row is the sole authority on lifetime, which is why a cookie that
  outlives its session simply fails.

**`SameSite=Lax`, not `Strict`.** This is the current architecture decision
(ADR-0005) and it is deliberate. `Strict` withholds the cookie on any
cross-site navigation, so following a link to the application from an email or
a chat message lands on a logged-out page even though a valid session exists.
`Lax` still withholds it from cross-site `POST`, which is the case that matters,
and CSRF protection here does not rest on the attribute anyway: it rests on the
session-bound token below.
"""

from __future__ import annotations

from typing import Final

from starlette.requests import Request
from starlette.responses import Response

from app.auth.sessions import IssuedSession
from app.core.settings import Settings

SESSION_COOKIE_NAME: Final = "session"
#: Named in docs/security.md §3. Readable by JavaScript by design.
CSRF_COOKIE_NAME: Final = "csrf_token"
CSRF_HEADER_NAME: Final = "X-CSRF-Token"

_COOKIE_PATH: Final = "/"
_SAME_SITE: Final = "lax"


def set_session_cookies(response: Response, issued: IssuedSession, settings: Settings) -> None:
    """Write both cookies for a freshly issued session."""
    secure = settings.cookies_are_secure
    response.set_cookie(
        SESSION_COOKIE_NAME,
        issued.token,
        httponly=True,
        secure=secure,
        samesite=_SAME_SITE,
        path=_COOKIE_PATH,
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        issued.csrf_token,
        # Readable from JavaScript on purpose: the client reads it and sends it
        # back as `X-CSRF-Token`. It is not a credential — on its own it
        # authenticates nothing, and it is only accepted alongside the session
        # cookie whose row holds its hash.
        httponly=False,
        secure=secure,
        samesite=_SAME_SITE,
        path=_COOKIE_PATH,
    )


def clear_session_cookies(response: Response, settings: Settings) -> None:
    """Expire both cookies on logout.

    The attributes are repeated because a browser matches a deletion by name,
    path and domain: a `Set-Cookie` with a different path would add a second,
    already-expired cookie and leave the original in place. This is only the
    tidy-up, though — the session was revoked in the database, so the old
    cookie is already useless whether or not the browser honours this.
    """
    secure = settings.cookies_are_secure
    for name, http_only in ((SESSION_COOKIE_NAME, True), (CSRF_COOKIE_NAME, False)):
        response.delete_cookie(
            name,
            path=_COOKIE_PATH,
            httponly=http_only,
            secure=secure,
            samesite=_SAME_SITE,
        )


def read_session_token(request: Request) -> str | None:
    """The raw session token from the cookie, or `None` if there is not one."""
    return request.cookies.get(SESSION_COOKIE_NAME) or None


def read_csrf_header(request: Request) -> str | None:
    """The submitted CSRF token.

    Read from the header only. The cookie of the same name is never consulted
    server-side: comparing the two would prove nothing beyond "the sender could
    set both", which is exactly what an attacker able to write cookies can do.
    The value is checked against the hash on the session row instead.
    """
    return request.headers.get(CSRF_HEADER_NAME) or None
