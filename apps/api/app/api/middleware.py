"""ASGI middleware.

Order, outermost first (docs/architecture.md §5):

    request context / id  →  access log  →  security headers  →  CORS  →  router

Written as plain ASGI middleware rather than `BaseHTTPMiddleware` so that the
streaming document downloads of Phase 6 are not buffered by the logging layer.
"""

from __future__ import annotations

import time
from typing import Final

import structlog
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import get_logger
from app.core.request_context import new_request_id, set_request_id

logger = get_logger(__name__)

#: Applied to every response. Deliberately short: this is a JSON API, so the
#: headers that matter are the ones that stop a browser from guessing a content
#: type or framing a response. The Content-Security-Policy belongs to the
#: Next.js application, which is what a browser actually renders, and HSTS
#: belongs to the TLS-terminating ingress (docs/security.md §8).
SECURITY_HEADERS: Final[dict[str, str]] = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-Frame-Options": "DENY",
}

REQUEST_ID_HEADER: Final = "X-Request-ID"


class RequestContextMiddleware:
    """Give every request an id, and put it on the logs and the response.

    An inbound `X-Request-ID` is ignored rather than honoured: trusting it would
    let a caller merge unrelated requests in the log or write arbitrary text
    into every line of it (ADR-0032).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = new_request_id()
        set_request_id(request_id)
        # Cleared at the start rather than unbound at the end: an unhandled
        # exception is turned into a response *outside* this middleware, and
        # that handler still needs the id for the envelope.
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        await self.app(scope, receive, send_with_request_id)


class AccessLogMiddleware:
    """One structured line per request: what was called, what came back, how long it took."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        status_code: int | None = None

        async def send_capturing_status(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, send_capturing_status)
        except BaseException:
            logger.exception(
                "http_request_failed",
                method=scope.get("method"),
                route=_route_of(scope),
                duration_ms=_elapsed_ms(started),
            )
            raise

        logger.info(
            "http_request",
            method=scope.get("method"),
            route=_route_of(scope),
            status_code=status_code,
            duration_ms=_elapsed_ms(started),
        )


class SecurityHeadersMiddleware:
    """Attach `SECURITY_HEADERS` to every response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_security_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    headers.setdefault(name, value)
            await send(message)

        await self.app(scope, receive, send_with_security_headers)


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


def _route_of(scope: Scope) -> str:
    """The matched route template, so log lines aggregate by endpoint.

    Built from the path and the resolved path parameters rather than read from
    `scope["route"]`, whose `path` is relative to the router that matched it and
    therefore loses the prefix of an included router. Whole segments are
    substituted, never substrings, and the query string never appears: from
    Phase 4 it carries search terms over personal data.
    """
    path = scope.get("path")
    if not isinstance(path, str):
        return ""
    params = scope.get("path_params") or {}
    if not params:
        return path
    placeholders = {str(value): "{" + name + "}" for name, value in params.items()}
    return "/".join(placeholders.get(segment, segment) for segment in path.split("/"))
