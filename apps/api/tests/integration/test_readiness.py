"""The readiness probe.

The failure path matters as much as the success path: an unavailable database
has to produce service-unavailable semantics and a body that tells an
unauthenticated caller nothing about the infrastructure behind it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.db.session import get_db_session
from tests.conftest import build_client

#: Nothing is listening on port 1, so the connection is refused immediately.
UNREACHABLE_DATABASE = "postgresql+asyncpg://nobody:nothing@127.0.0.1:1/nowhere"


@pytest.fixture
async def client_without_a_database(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """A real, genuinely unreachable database rather than a stubbed session."""
    engine = create_async_engine(
        UNREACHABLE_DATABASE, poolclass=NullPool, connect_args={"timeout": 2}
    )

    async def _override() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(bind=engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = _override
    try:
        async with build_client(app) as async_client:
            yield async_client
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest.mark.parametrize("path", ["/readyz", "/api/v1/readyz"])
async def test_ready_when_the_database_answers(db_client: AsyncClient, path: str) -> None:
    response = await db_client.get(path)

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


async def test_the_ready_response_discloses_nothing_else(db_client: AsyncClient) -> None:
    response = await db_client.get("/readyz")

    assert list(response.json()) == ["status"]


class TestWhenTheDatabaseIsUnavailable:
    async def test_the_probe_reports_service_unavailable(
        self, client_without_a_database: AsyncClient
    ) -> None:
        response = await client_without_a_database.get("/readyz")

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"

    async def test_the_body_leaks_no_infrastructure_detail(
        self, client_without_a_database: AsyncClient
    ) -> None:
        response = await client_without_a_database.get("/readyz")
        body = response.text

        for leak in ("127.0.0.1", "nowhere", "nobody", "nothing", "asyncpg", "postgres", "Connect"):
            assert leak not in body

    async def test_liveness_is_unaffected(self, client_without_a_database: AsyncClient) -> None:
        """A dependency outage must not get the container restarted."""
        response = await client_without_a_database.get("/healthz")

        assert response.status_code == 200
