"""CSRF protection (docs/security.md §3).

The design being proved here is *session-bound* double submit: the submitted
header is hashed and compared against the hash on the caller's own session row.
A plain "cookie equals header" comparison would pass every test in the first
class below and still be broken, which is exactly what the session-binding
tests at the bottom exist to catch.
"""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cookies import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, SESSION_COOKIE_NAME
from app.audit.actions import AuditAction
from app.auth.tokens import generate_csrf_token
from app.models.activity_log import ActivityLog
from tests.support.accounts import (
    ADMIN_PASSWORD,
    EMPLOYEE_PASSWORD,
    create_admin,
    create_employee,
    csrf_headers,
    log_in,
)


class TestUnsafeMethodsRequireIt:
    async def test_a_post_without_the_header_is_refused(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await create_employee(db_session)
        await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        response = await db_client.post("/api/v1/auth/logout")

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "CSRF_TOKEN_INVALID"

    async def test_a_post_with_a_wrong_header_is_refused(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await create_employee(db_session)
        await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        response = await db_client.post(
            "/api/v1/auth/logout", headers=csrf_headers(generate_csrf_token())
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "CSRF_TOKEN_INVALID"

    async def test_an_empty_header_is_refused(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await create_employee(db_session)
        await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        response = await db_client.post("/api/v1/auth/logout", headers={CSRF_HEADER_NAME: ""})

        assert response.status_code == 403

    async def test_the_matching_header_is_accepted(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await create_employee(db_session)
        token = await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        response = await db_client.post("/api/v1/auth/logout", headers=csrf_headers(token))

        assert response.status_code == 204

    async def test_a_patch_needs_it_too(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin = await create_admin(db_session)
        await log_in(db_client, email=admin.email, password=ADMIN_PASSWORD)

        response = await db_client.patch(
            f"/api/v1/users/{admin.id}", json={"full_name": "Renamed Person"}
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "CSRF_TOKEN_INVALID"

    async def test_the_cookie_alone_is_not_enough(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The cookie is never read server-side — an attacker who can set cookies
        must still not be able to act, which is the flaw in stateless double submit."""
        await create_employee(db_session)
        await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        response = await db_client.post("/api/v1/auth/logout")

        assert response.status_code == 403
        assert CSRF_COOKIE_NAME in db_client.cookies


class TestSafeMethodsDoNotRequireIt:
    async def test_a_get_needs_no_token(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A safe method changes nothing, so there is nothing for CSRF to protect."""
        await create_employee(db_session)
        await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        assert (await db_client.get("/api/v1/auth/me")).status_code == 200

    async def test_a_get_with_a_wrong_token_is_not_refused(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The check does not run at all on safe methods, rather than running and passing."""
        await create_employee(db_session)
        await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        response = await db_client.get(
            "/api/v1/auth/me", headers=csrf_headers("a-completely-wrong-token")
        )

        assert response.status_code == 200

    async def test_the_operational_probes_are_unaffected(self, db_client: AsyncClient) -> None:
        assert (await db_client.get("/healthz")).status_code == 200


class TestOrderOfChecks:
    async def test_an_unauthenticated_post_is_401_not_403(self, db_client: AsyncClient) -> None:
        """Authentication first: "who are you" precedes "prove this was intentional"."""
        response = await db_client.post("/api/v1/auth/logout")

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "AUTH_REQUIRED"

    async def test_login_itself_needs_no_token(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """There is no session to bind a token to yet, and no authority to abuse."""
        await create_employee(db_session)

        response = await db_client.post(
            "/api/v1/auth/login",
            json={"email": "employee@example.com", "password": EMPLOYEE_PASSWORD},
        )

        assert response.status_code == 204

    async def test_a_revoked_session_fails_authentication_before_csrf(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await create_employee(db_session)
        token = await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)
        await db_client.post("/api/v1/auth/logout", headers=csrf_headers(token))

        response = await db_client.post("/api/v1/auth/logout", headers=csrf_headers(token))

        assert response.status_code == 401


class TestSessionBinding:
    """FLOW F: a token is only good for the session it was issued with."""

    async def test_a_token_from_another_session_is_refused(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await create_employee(db_session, email="employee@example.com")

        token_a = await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)
        db_client.cookies.clear()
        await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        response = await db_client.post("/api/v1/auth/logout", headers=csrf_headers(token_a))

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "CSRF_TOKEN_INVALID"

    async def test_a_token_from_another_user_is_refused(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin = await create_admin(db_session)
        await create_employee(db_session)

        admin_token = await log_in(db_client, email=admin.email, password=ADMIN_PASSWORD)
        db_client.cookies.clear()
        await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        response = await db_client.post("/api/v1/auth/logout", headers=csrf_headers(admin_token))

        assert response.status_code == 403

    async def test_a_session_cookie_paired_with_its_own_token_still_works(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The negative tests above would also pass if everything were refused."""
        await create_employee(db_session, email="employee@example.com")
        token_a = await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)
        cookie_a = db_client.cookies[SESSION_COOKIE_NAME]

        db_client.cookies.clear()
        await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)
        db_client.cookies.set(SESSION_COOKIE_NAME, cookie_a)

        response = await db_client.post("/api/v1/auth/logout", headers=csrf_headers(token_a))

        assert response.status_code == 204

    async def test_a_new_session_gets_a_new_token(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await create_employee(db_session, email="employee@example.com")

        first = await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)
        db_client.cookies.clear()
        second = await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        assert first != second


class TestAuditing:
    async def test_a_rejected_token_is_recorded(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """It is either an attack or a client bug, and both are worth seeing later."""
        await create_employee(db_session)
        await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        await db_client.post("/api/v1/auth/logout", headers=csrf_headers(generate_csrf_token()))

        entry = await db_session.scalar(
            select(ActivityLog).where(
                ActivityLog.action == AuditAction.CSRF_VALIDATION_FAILED.value
            )
        )
        assert entry is not None

    async def test_the_recorded_event_contains_no_token_material(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Neither what was offered nor what was expected: the event is that it failed."""
        await create_employee(db_session)
        await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)
        submitted = generate_csrf_token()

        await db_client.post("/api/v1/auth/logout", headers=csrf_headers(submitted))

        entry = await db_session.scalar(
            select(ActivityLog).where(
                ActivityLog.action == AuditAction.CSRF_VALIDATION_FAILED.value
            )
        )
        assert entry is not None
        rendered = f"{entry.description} {entry.event_metadata}"
        assert submitted not in rendered
        assert db_client.cookies[CSRF_COOKIE_NAME] not in rendered

    async def test_the_session_survives_a_rejected_token(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A failed CSRF check is not a reason to log somebody out."""
        await create_employee(db_session)
        token = await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        await db_client.post("/api/v1/auth/logout", headers=csrf_headers(generate_csrf_token()))

        assert (await db_client.get("/api/v1/auth/me")).status_code == 200
        assert (
            await db_client.post("/api/v1/auth/logout", headers=csrf_headers(token))
        ).status_code == 204
