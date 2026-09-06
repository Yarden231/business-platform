"""Who may call what (docs/security.md §4).

Authorization is asserted over HTTP, at the endpoints, because that is where it
has to hold: the pure policy functions are already unit tested, and a passing
unit test says nothing about a route that forgot to depend on them.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import UserRole
from tests.support.accounts import (
    ADMIN_PASSWORD,
    EMPLOYEE_PASSWORD,
    create_admin,
    create_employee,
    csrf_headers,
    log_in,
)

#: Every admin-only endpoint, as a callable an unprivileged caller can attempt.
ADMIN_ONLY: dict[str, Callable[[AsyncClient, str, str], Awaitable[Response]]] = {
    "list users": lambda client, _target, _token: client.get("/api/v1/users"),
    "read a user": lambda client, target, _token: client.get(f"/api/v1/users/{target}"),
    "create a user": lambda client, _target, token: client.post(
        "/api/v1/users",
        json={
            "email": "new-hire@example.com",
            "full_name": "New Hire",
            "role": "EMPLOYEE",
        },
        headers=csrf_headers(token),
    ),
    "update a user": lambda client, target, token: client.patch(
        f"/api/v1/users/{target}",
        json={"full_name": "Renamed"},
        headers=csrf_headers(token),
    ),
    "reset a password": lambda client, target, token: client.post(
        f"/api/v1/users/{target}/password-reset", headers=csrf_headers(token)
    ),
}


class TestUnauthenticatedCallers:
    @pytest.mark.parametrize("endpoint", sorted(ADMIN_ONLY))
    async def test_they_cannot_reach_user_administration(
        self, db_client: AsyncClient, db_session: AsyncSession, endpoint: str
    ) -> None:
        target = await create_admin(db_session)

        response = await ADMIN_ONLY[endpoint](db_client, str(target.id), "no-token")

        assert response.status_code == 401
        assert response.json()["error"]["code"] in {"AUTH_REQUIRED", "CSRF_TOKEN_INVALID"}

    async def test_they_cannot_read_their_own_identity(self, db_client: AsyncClient) -> None:
        response = await db_client.get("/api/v1/auth/me")

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "AUTH_REQUIRED"

    async def test_they_cannot_read_the_staff_directory(self, db_client: AsyncClient) -> None:
        assert (await db_client.get("/api/v1/users/directory")).status_code == 401

    async def test_they_cannot_change_a_password(self, db_client: AsyncClient) -> None:
        response = await db_client.post(
            "/api/v1/auth/password",
            json={"current_password": "whatever", "new_password": "a new long password"},
        )

        assert response.status_code == 401

    async def test_the_refusal_reveals_nothing_about_the_target(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A real and an invented user id must be indistinguishable to a stranger."""
        real = await create_admin(db_session)

        existing = await db_client.get(f"/api/v1/users/{real.id}")
        invented = await db_client.get("/api/v1/users/0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0")

        assert existing.status_code == invented.status_code == 401
        assert existing.json()["error"]["code"] == invented.json()["error"]["code"]


class TestEmployees:
    @pytest.fixture
    async def employee_client(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> tuple[AsyncClient, str]:
        await create_employee(db_session, email="employee@example.com")
        token = await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)
        return db_client, token

    @pytest.mark.parametrize("endpoint", sorted(ADMIN_ONLY))
    async def test_they_cannot_administer_users(
        self,
        employee_client: tuple[AsyncClient, str],
        db_session: AsyncSession,
        endpoint: str,
    ) -> None:
        client, token = employee_client
        target = await create_admin(db_session)

        response = await ADMIN_ONLY[endpoint](client, str(target.id), token)

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "FORBIDDEN"

    async def test_they_cannot_reset_their_own_password_through_the_admin_route(
        self, employee_client: tuple[AsyncClient, str], db_session: AsyncSession
    ) -> None:
        """Self-service goes through `/auth/password`, which needs the current password."""
        client, token = employee_client
        me = (await client.get("/api/v1/auth/me")).json()

        response = await client.post(
            f"/api/v1/users/{me['id']}/password-reset", headers=csrf_headers(token)
        )

        assert response.status_code == 403

    async def test_they_cannot_promote_themselves(
        self, employee_client: tuple[AsyncClient, str]
    ) -> None:
        client, token = employee_client
        me = (await client.get("/api/v1/auth/me")).json()

        response = await client.patch(
            f"/api/v1/users/{me['id']}",
            json={"role": "ADMIN"},
            headers=csrf_headers(token),
        )

        assert response.status_code == 403

    async def test_they_can_read_their_own_identity(
        self, employee_client: tuple[AsyncClient, str]
    ) -> None:
        client, _token = employee_client

        response = await client.get("/api/v1/auth/me")

        assert response.status_code == 200
        assert response.json()["role"] == UserRole.EMPLOYEE.value

    async def test_they_can_read_the_staff_directory(
        self, employee_client: tuple[AsyncClient, str]
    ) -> None:
        """The one shared endpoint: an employee has to see who to assign work to."""
        client, _token = employee_client

        response = await client.get("/api/v1/users/directory")

        assert response.status_code == 200

    async def test_they_can_change_their_own_password(
        self, employee_client: tuple[AsyncClient, str]
    ) -> None:
        client, token = employee_client

        response = await client.post(
            "/api/v1/auth/password",
            json={
                "current_password": EMPLOYEE_PASSWORD,
                "new_password": "a brand new long password",
            },
            headers=csrf_headers(token),
        )

        assert response.status_code == 204

    async def test_they_can_log_out(self, employee_client: tuple[AsyncClient, str]) -> None:
        client, token = employee_client

        assert (
            await client.post("/api/v1/auth/logout", headers=csrf_headers(token))
        ).status_code == 204


class TestAdmins:
    @pytest.fixture
    async def admin_client(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> tuple[AsyncClient, str]:
        await create_admin(db_session, email="admin@example.com")
        token = await log_in(db_client, email="admin@example.com", password=ADMIN_PASSWORD)
        return db_client, token

    @pytest.mark.parametrize("endpoint", sorted(ADMIN_ONLY))
    async def test_they_can_administer_users(
        self,
        admin_client: tuple[AsyncClient, str],
        db_session: AsyncSession,
        endpoint: str,
    ) -> None:
        client, token = admin_client
        target = await create_employee(db_session, email="target@example.com")

        response = await ADMIN_ONLY[endpoint](client, str(target.id), token)

        assert response.status_code < 400, response.text

    async def test_they_can_read_the_staff_directory_too(
        self, admin_client: tuple[AsyncClient, str]
    ) -> None:
        client, _token = admin_client

        assert (await client.get("/api/v1/users/directory")).status_code == 200


class TestDeactivatedUsers:
    async def test_they_cannot_establish_a_new_session(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await create_employee(db_session, email="gone@example.com", deactivated=True)

        response = await db_client.post(
            "/api/v1/auth/login",
            json={"email": "gone@example.com", "password": EMPLOYEE_PASSWORD},
        )

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "AUTH_INVALID_CREDENTIALS"

    async def test_their_existing_session_stops_working(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        from app.core.time import utc_now

        user = await create_employee(db_session)
        await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        user.deactivated_at = utc_now()
        await db_session.flush()

        response = await db_client.get("/api/v1/auth/me")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "AUTH_ACCOUNT_INACTIVE"
