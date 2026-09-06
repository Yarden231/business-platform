"""The transaction boundary.

    router  →  service  →  repository / models  →  database
               ^^^^^^^
               owns the transaction

Routers never commit. Repositories never commit. A service wraps the whole use
case in `transaction(session)`, and everything inside it — the business rows and
the `activity_log` row the audit recorder writes — commits together or not at
all. That single property is what makes the audit trail evidence rather than a
best effort (ADR-0010).

    async with transaction(self._session):
        case.status = to_status
        await self._audit.record(...)

There is deliberately no repository registry, no `UnitOfWork` object holding
half the application, and no decorator magic: the session is already the unit of
work, and this is the marker that says where it is committed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession


@asynccontextmanager
async def transaction(session: AsyncSession) -> AsyncIterator[AsyncSession]:
    """Commit the session's work on success, roll all of it back on any failure.

    The session's implicit transaction is used rather than an explicit `begin()`,
    so this composes with a caller that has already begun one — which is what
    the integration-test harness does to keep every test isolated.
    """
    try:
        yield session
    except BaseException:
        await session.rollback()
        raise
    else:
        await session.commit()
