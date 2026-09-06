"""One `AsyncSession` per request.

The session is created when the request starts and closed when it ends. It is
handed to services, which are the only code allowed to commit
(`app.db.uow`). Anything still uncommitted when the request finishes is rolled
back, which makes a read-only request exactly that: a transaction that leaves no
trace.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.engine import get_engine

_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """The shared session factory for this process."""
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            autoflush=False,
        )
    return _sessionmaker


def reset_sessionmaker() -> None:
    """Forget the cached factory. Used when the engine is disposed."""
    global _sessionmaker
    _sessionmaker = None


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding the request-scoped session."""
    async with get_sessionmaker()() as session:
        try:
            yield session
        finally:
            # A service that finished its work has already committed; this
            # discards anything a read-only path or a failed request left open.
            await session.rollback()
