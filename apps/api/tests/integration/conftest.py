"""Database fixtures.

Isolation is transaction-per-test: the fixture opens a connection, begins a
transaction, binds the session to it, and rolls it back afterwards. Nothing a
test writes survives, so tests are order-independent and the database does not
have to be rebuilt between them. Because the session joins the outer
transaction with `create_savepoint`, a service under test can call `commit()`
for real — releasing a savepoint — and the outer rollback still discards
everything.

One documented exception is coming: the case-number concurrency test in Phase 5
has to prove that two *independent, committing* sessions cannot allocate the
same number, which by definition cannot happen inside one transaction. That test
will use its own connections and clean up after itself (docs/architecture.md §11).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.db.session import get_db_session
from tests.conftest import build_client
from tests.support.database import ensure_database, integration_database_url, upgrade_to_head


@pytest.fixture(scope="session")
def migrated_database() -> str:
    """Create the test database if needed and bring it to the migration head.

    Deliberately a synchronous fixture: Alembic's `command.upgrade` runs the
    async migration environment with `asyncio.run`, which is only legal outside
    a running event loop.
    """
    url = integration_database_url()
    ensure_database(url)
    upgrade_to_head(url)
    return url


@pytest.fixture
async def db_engine(migrated_database: str) -> AsyncIterator[AsyncEngine]:
    """A per-test engine.

    `NullPool` and a fresh engine per test because asyncpg connections belong to
    the event loop that opened them, and every test gets its own loop.
    """
    engine = create_async_engine(migrated_database, poolclass=NullPool)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """A session inside a transaction that is rolled back when the test ends."""
    async with db_engine.connect() as connection:
        outer = await connection.begin()
        session = AsyncSession(
            bind=connection,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
            autoflush=False,
        )
        try:
            yield session
        finally:
            await session.close()
            if outer.is_active:
                await outer.rollback()


@pytest.fixture
async def db_client(app: FastAPI, db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """An HTTP client whose requests run in the test's transaction."""

    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db_session] = _override
    try:
        async with build_client(app) as async_client:
            yield async_client
    finally:
        app.dependency_overrides.clear()
