"""The process-wide async engine.

Created on first use rather than at import time, so importing `app.main` — which
the test suite, `alembic` and tooling all do — never opens a socket. Disposed by
the application lifespan.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.settings import Settings, get_settings

_engine: AsyncEngine | None = None


def create_engine(settings: Settings) -> AsyncEngine:
    """Build an engine from settings. Callers that want the shared one use `get_engine`."""
    return create_async_engine(
        settings.database_url,
        echo=settings.db_echo,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_recycle=settings.db_pool_recycle_seconds,
        # A connection that died while idle (a database restart, a load
        # balancer timeout) is replaced instead of failing the request that
        # happens to draw it from the pool.
        pool_pre_ping=True,
        connect_args={"timeout": settings.db_connect_timeout_seconds},
    )


def get_engine() -> AsyncEngine:
    """The shared engine for this process."""
    global _engine
    if _engine is None:
        _engine = create_engine(get_settings())
    return _engine


async def dispose_engine() -> None:
    """Close every pooled connection. Called on application shutdown."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
