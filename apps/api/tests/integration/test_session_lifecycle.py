"""Session resolution, expiry, refresh throttling and revocation (docs/security.md §3).

Expiry is tested by backdating the session row rather than by waiting out an
eight-hour idle window. The *rules* are unit tested directly against
`app.domain.sessions`; what these tests prove is that the resolution path
actually applies them, and that the server-side row — not the cookie — is what
decides.
"""

from __future__ import annotations

from datetime import timedelta

from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cookies import SESSION_COOKIE_NAME
from app.core.settings import get_settings
from app.core.time import utc_now
from tests.support.accounts import (
    EMPLOYEE_PASSWORD,
    age_session,
    create_employee,
    hours_ago,
    log_in,
    stored_sessions,
)


async def me(client: AsyncClient) -> Response:
    return await client.get("/api/v1/auth/me")


class TestResolution:
    async def test_a_valid_session_identifies_the_caller(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user = await create_employee(db_session)
        await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        response = await me(db_client)

        assert response.status_code == 200
        assert response.json()["id"] == str(user.id)

    async def test_no_cookie_is_unauthenticated(self, db_client: AsyncClient) -> None:
        response = await me(db_client)

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "AUTH_REQUIRED"

    async def test_a_made_up_cookie_is_unauthenticated(self, db_client: AsyncClient) -> None:
        """The lookup is by hash, so a guessed token simply matches no row."""
        db_client.cookies.set(SESSION_COOKIE_NAME, "not-a-real-session-token")

        response = await me(db_client)

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "AUTH_REQUIRED"

    async def test_an_empty_cookie_is_unauthenticated(self, db_client: AsyncClient) -> None:
        db_client.cookies.set(SESSION_COOKIE_NAME, "")

        assert (await me(db_client)).status_code == 401

    async def test_another_users_session_identifies_that_other_user(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Sanity check that the actor comes from the session row, not the request."""
        await create_employee(db_session, email="first@example.com")
        second = await create_employee(db_session, email="second@example.com")
        await log_in(db_client, email="second@example.com", password=EMPLOYEE_PASSWORD)

        assert (await me(db_client)).json()["email"] == second.email


class TestAbsoluteExpiry:
    async def test_a_session_past_its_absolute_lifetime_is_refused(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user = await create_employee(db_session)
        await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)
        session_row = (await stored_sessions(db_session, user.id))[0]

        await age_session(db_session, session_row, expires=hours_ago(1))

        response = await me(db_client)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "AUTH_SESSION_EXPIRED"

    async def test_recent_use_does_not_extend_it(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Twelve hours is a cap, not a rolling window."""
        user = await create_employee(db_session)
        await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)
        session_row = (await stored_sessions(db_session, user.id))[0]

        await age_session(db_session, session_row, expires=hours_ago(1), last_seen=utc_now())

        assert (await me(db_client)).status_code == 401


class TestIdleExpiry:
    async def test_a_session_idle_beyond_the_window_is_refused(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user = await create_employee(db_session)
        await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)
        session_row = (await stored_sessions(db_session, user.id))[0]
        idle_hours = get_settings().session_idle_timeout_seconds / 3600

        await age_session(db_session, session_row, last_seen=hours_ago(idle_hours + 1))

        response = await me(db_client)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "AUTH_SESSION_EXPIRED"

    async def test_a_session_inside_the_window_is_still_good(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user = await create_employee(db_session)
        await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)
        session_row = (await stored_sessions(db_session, user.id))[0]
        idle_hours = get_settings().session_idle_timeout_seconds / 3600

        await age_session(db_session, session_row, last_seen=hours_ago(idle_hours - 1))

        assert (await me(db_client)).status_code == 200

    async def test_an_idle_expired_session_is_not_resurrected_by_a_later_request(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The refresh must not run before the check, or the timeout could never fire."""
        user = await create_employee(db_session)
        await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)
        session_row = (await stored_sessions(db_session, user.id))[0]
        idle_hours = get_settings().session_idle_timeout_seconds / 3600
        await age_session(db_session, session_row, last_seen=hours_ago(idle_hours + 1))

        await me(db_client)

        assert (await me(db_client)).status_code == 401


class TestRefreshThrottling:
    async def test_a_stale_session_has_its_idle_clock_refreshed(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user = await create_employee(db_session)
        await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)
        session_row = (await stored_sessions(db_session, user.id))[0]
        await age_session(db_session, session_row, last_seen=hours_ago(1))
        before = session_row.last_seen_at

        assert (await me(db_client)).status_code == 200

        await db_session.refresh(session_row)
        assert session_row.last_seen_at > before

    async def test_a_fresh_session_is_not_written_again(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Otherwise every authenticated read would cost an UPDATE (docs/security.md §3)."""
        user = await create_employee(db_session)
        await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)
        session_row = (await stored_sessions(db_session, user.id))[0]
        before = session_row.last_seen_at

        for _ in range(3):
            assert (await me(db_client)).status_code == 200

        await db_session.refresh(session_row)
        assert session_row.last_seen_at == before

    async def test_the_refresh_does_not_move_the_absolute_expiry(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user = await create_employee(db_session)
        await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)
        session_row = (await stored_sessions(db_session, user.id))[0]
        await age_session(db_session, session_row, last_seen=hours_ago(1))
        expires_at = session_row.expires_at

        await me(db_client)

        await db_session.refresh(session_row)
        assert session_row.expires_at == expires_at


class TestRevocation:
    async def test_a_revoked_session_stops_working_immediately(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user = await create_employee(db_session)
        await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)
        session_row = (await stored_sessions(db_session, user.id))[0]

        session_row.revoked_at = utc_now()
        await db_session.flush()

        response = await me(db_client)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "AUTH_SESSION_EXPIRED"

    async def test_revocation_beats_a_session_that_is_otherwise_valid(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Nothing about the timestamps can rescue a revoked row (ADR-0004)."""
        user = await create_employee(db_session)
        await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)
        session_row = (await stored_sessions(db_session, user.id))[0]

        session_row.revoked_at = utc_now()
        session_row.last_seen_at = utc_now()
        session_row.expires_at = utc_now() + timedelta(hours=12)
        await db_session.flush()

        assert (await me(db_client)).status_code == 401


class TestDeactivatedUsers:
    async def test_a_deactivated_user_cannot_use_an_existing_session(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Belt and braces: deactivation revokes sessions, and resolution re-checks."""
        user = await create_employee(db_session)
        await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        user.deactivated_at = utc_now()
        await db_session.flush()

        response = await me(db_client)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "AUTH_ACCOUNT_INACTIVE"
