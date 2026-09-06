"""Per-IP login throttling (docs/security.md §2).

This is the second brute-force control: the per-identity lockout stops guessing
at one account, and this stops one source spraying many. The counter is the
trailing window of `USER_LOGIN_FAILED` rows, so these tests set the limit low
through configuration rather than making twenty requests.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cookies import SESSION_COOKIE_NAME
from app.core.settings import get_settings
from app.db.session import get_db_session
from app.main import create_app
from tests.conftest import build_client
from tests.support.accounts import EMPLOYEE_PASSWORD, create_employee


@pytest.fixture
async def throttled_client(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> AsyncIterator[AsyncClient]:
    """A client whose source address is allowed three failures."""
    monkeypatch.setenv("LOGIN_IP_MAX_FAILED_ATTEMPTS", "3")
    monkeypatch.setenv("LOGIN_MAX_FAILED_ATTEMPTS", "100")  # keep the two controls apart
    get_settings.cache_clear()
    app: FastAPI = create_app()

    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db_session] = _override
    async with build_client(app) as client:
        yield client
    get_settings.cache_clear()


async def fail_login(client: AsyncClient, email: str = "employee@example.com") -> Response:
    return await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "wrong-password"}
    )


class TestThrottling:
    async def test_attempts_within_the_allowance_are_answered_normally(
        self, throttled_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await create_employee(db_session)

        for _ in range(3):
            response = await fail_login(throttled_client)
            assert response.status_code == 401

    async def test_the_next_attempt_is_refused_as_too_many_requests(
        self, throttled_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await create_employee(db_session)
        for _ in range(3):
            await fail_login(throttled_client)

        response = await fail_login(throttled_client)

        assert response.status_code == 429
        assert response.json()["error"]["code"] == "TOO_MANY_REQUESTS"

    async def test_it_counts_failures_across_different_accounts(
        self, throttled_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The point of this control: no per-identity counter can see spraying."""
        await create_employee(db_session, email="one@example.com")
        await create_employee(db_session, email="two@example.com")

        await fail_login(throttled_client, "one@example.com")
        await fail_login(throttled_client, "two@example.com")
        await fail_login(throttled_client, "nobody@example.com")

        assert (await fail_login(throttled_client, "one@example.com")).status_code == 429

    async def test_a_throttled_caller_cannot_log_in_even_with_the_right_password(
        self, throttled_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await create_employee(db_session)
        for _ in range(3):
            await fail_login(throttled_client)

        response = await throttled_client.post(
            "/api/v1/auth/login",
            json={"email": "employee@example.com", "password": EMPLOYEE_PASSWORD},
        )

        assert response.status_code == 429
        assert SESSION_COOKIE_NAME not in throttled_client.cookies

    async def test_successful_logins_are_not_counted(
        self, throttled_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await create_employee(db_session)

        for _ in range(5):
            response = await throttled_client.post(
                "/api/v1/auth/login",
                json={"email": "employee@example.com", "password": EMPLOYEE_PASSWORD},
            )
            assert response.status_code == 204
            throttled_client.cookies.clear()

    async def test_the_refusal_leaks_nothing_about_the_accounts_tried(
        self, throttled_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await create_employee(db_session)
        for _ in range(3):
            await fail_login(throttled_client)

        response = await fail_login(throttled_client, "employee@example.com")

        assert "employee@example.com" not in response.text

    async def test_an_authenticated_request_is_unaffected(
        self, throttled_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The throttle guards the login endpoint, not the whole API."""
        await create_employee(db_session)
        await throttled_client.post(
            "/api/v1/auth/login",
            json={"email": "employee@example.com", "password": EMPLOYEE_PASSWORD},
        )
        for _ in range(4):
            await fail_login(throttled_client, "nobody@example.com")

        assert (await throttled_client.get("/api/v1/auth/me")).status_code == 200
