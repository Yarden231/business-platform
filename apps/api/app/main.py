"""FastAPI application entry point.

Assembles the platform built in Phase 1: typed settings, structured logging,
request ids, the error envelope, security headers, the database session
lifecycle and the two operational probes. It contains no business logic and,
after Phase 1, no route definitions either — routers live in `app.api.routers`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Final

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.api.exception_handlers import register_exception_handlers
from app.api.middleware import (
    AccessLogMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from app.api.routers.auth import router as auth_router
from app.api.routers.operational import router as operational_router
from app.api.routers.users import router as users_router
from app.core.logging import configure_logging, get_logger
from app.core.settings import Settings, get_settings
from app.db.engine import dispose_engine
from app.db.session import reset_sessionmaker
from app.schemas.errors import ErrorEnvelope

API_V1_PREFIX: Final = "/api/v1"

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start-up and shut-down.

    Settings are validated before this runs — `create_app` builds them — so an
    unsafe production configuration fails at import rather than after the port
    is bound. No connection is opened here on purpose: an API instance that
    starts while the database is briefly unavailable should report itself
    not-ready and recover, not fail to start.
    """
    settings = get_settings()
    logger.info(
        "api_starting",
        app_env=settings.app_env.value,
        docs_enabled=settings.docs_enabled,
        version=app.version,
    )
    try:
        yield
    finally:
        await dispose_engine()
        reset_sessionmaker()
        logger.info("api_stopped")


def _register_middleware(app: FastAPI, settings: Settings) -> None:
    """Install the middleware stack.

    Starlette applies the *last* registered middleware outermost, so these are
    added in reverse of the documented order (docs/architecture.md §5):
    request context, then the access log, then security headers, then CORS.
    """
    if settings.cors_allowed_origins:
        # Never a wildcard, and never with credentials against one — the
        # settings validator makes that combination unrepresentable. In
        # production the list is empty and this middleware is not installed at
        # all, because the browser reaches the API through the same-origin
        # proxy (ADR-0005).
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allowed_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
            max_age=600,
        )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(RequestContextMiddleware)


def create_app() -> FastAPI:
    """Build the application. One call per process; tests use it to get a clean instance."""
    settings = get_settings()
    configure_logging(settings)

    app = FastAPI(
        title="Cohen Financial Balancing API",
        version="0.1.0",
        lifespan=lifespan,
        debug=settings.debug,
        # Interactive documentation and the OpenAPI document are available
        # outside production only (docs/security.md §8).
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        responses={500: {"model": ErrorEnvelope, "description": "Unexpected server error."}},
    )

    _register_middleware(app, settings)
    register_exception_handlers(app)

    # The operational router is mounted twice from one set of handlers:
    #   /healthz, /readyz                 infrastructure probes, unversioned and
    #                                     kept out of the published contract;
    #   /api/v1/healthz, /api/v1/readyz   the same checks as the browser reaches
    #                                     them, through the web origin's
    #                                     same-origin proxy (ADR-0005).
    app.include_router(operational_router, include_in_schema=False)
    app.include_router(operational_router, prefix=API_V1_PREFIX)

    # Everything else is versioned only. There is no unversioned alias for an
    # application endpoint: the browser reaches all of these through the
    # same-origin `/api/v1/*` proxy (ADR-0005).
    app.include_router(auth_router, prefix=API_V1_PREFIX)
    app.include_router(users_router, prefix=API_V1_PREFIX)
    return app


app = create_app()
