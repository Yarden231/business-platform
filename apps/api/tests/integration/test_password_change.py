"""`POST /auth/password` and the forced-rotation gate (docs/api.md §5, ADR-0026).

The interesting part is the sequencing: a successful change revokes every
existing session *and* issues a fresh one, so the caller who just rotated their
password stays logged in while every other browser holding the old session does
not.
"""

from __future__ import annotations

from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cookies import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
from app.audit.actions import AuditAction
from app.auth.hashing import get_password_hasher
from app.core.settings import get_settings
from app.models.activity_log import ActivityLog
from tests.support.accounts import (
    EMPLOYEE_PASSWORD,
    create_employee,
    csrf_headers,
    log_in,
    password_identity,
    stored_sessions,
)

NEW_PASSWORD = "a brand new long passphrase"


async def change_password(
    client: AsyncClient,
    token: str,
    *,
    current: str = EMPLOYEE_PASSWORD,
    new: str = NEW_PASSWORD,
) -> Response:
    return await client.post(
        "/api/v1/auth/password",
        json={"current_password": current, "new_password": new},
        headers=csrf_headers(token),
    )


class TestSuccessfulChange:
    async def test_it_answers_204(self, db_client: AsyncClient, db_session: AsyncSession) -> None:
        await create_employee(db_session)
        token = await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        assert (await change_password(db_client, token)).status_code == 204

    async def test_the_new_password_works_and_the_old_one_does_not(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await create_employee(db_session)
        token = await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)
        await change_password(db_client, token)

        db_client.cookies.clear()
        old = await db_client.post(
            "/api/v1/auth/login",
            json={"email": "employee@example.com", "password": EMPLOYEE_PASSWORD},
        )
        new = await db_client.post(
            "/api/v1/auth/login",
            json={"email": "employee@example.com", "password": NEW_PASSWORD},
        )

        assert old.status_code == 401
        assert new.status_code == 204

    async def test_only_the_new_hash_is_stored(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user = await create_employee(db_session)
        token = await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        await change_password(db_client, token)

        identity = await password_identity(db_session, user.id)
        await db_session.refresh(identity)
        assert identity.secret_hash is not None
        assert NEW_PASSWORD not in identity.secret_hash
        hasher = get_password_hasher(get_settings())
        assert hasher.verify_password(password=NEW_PASSWORD, secret_hash=identity.secret_hash)
        assert not hasher.verify_password(
            password=EMPLOYEE_PASSWORD, secret_hash=identity.secret_hash
        )

    async def test_it_records_when_the_secret_changed(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user = await create_employee(db_session)
        identity = await password_identity(db_session, user.id)
        before = identity.secret_updated_at
        token = await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        await change_password(db_client, token)

        await db_session.refresh(identity)
        assert before is not None
        assert identity.secret_updated_at is not None
        assert identity.secret_updated_at >= before

    async def test_the_caller_keeps_working_on_a_fresh_session(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Revoke-then-issue, not issue-then-revoke: the order is the difference
        between staying logged in and logging yourself out."""
        await create_employee(db_session)
        token = await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)
        before = db_client.cookies[SESSION_COOKIE_NAME]

        await change_password(db_client, token)

        assert db_client.cookies[SESSION_COOKIE_NAME] != before
        assert (await db_client.get("/api/v1/auth/me")).status_code == 200

    async def test_the_csrf_token_is_reissued_too(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The old token is bound to the revoked session, so it must be replaced."""
        await create_employee(db_session)
        token = await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        await change_password(db_client, token)

        assert db_client.cookies[CSRF_COOKIE_NAME] != token
        assert (
            await db_client.post(
                "/api/v1/auth/logout",
                headers=csrf_headers(db_client.cookies[CSRF_COOKIE_NAME]),
            )
        ).status_code == 204

    async def test_it_clears_any_lockout(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Rotating the password proves ownership, so the old failures are spent."""
        user = await create_employee(db_session)
        token = await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)
        identity = await password_identity(db_session, user.id)
        identity.failed_attempt_count = 3
        await db_session.flush()

        await change_password(db_client, token)

        await db_session.refresh(identity)
        assert identity.failed_attempt_count == 0
        assert identity.locked_until is None

    async def test_it_is_audited_without_either_password(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user = await create_employee(db_session)
        token = await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        await change_password(db_client, token)

        entry = await db_session.scalar(
            select(ActivityLog).where(ActivityLog.action == AuditAction.USER_PASSWORD_CHANGED.value)
        )
        assert entry is not None
        assert entry.actor_user_id == user.id
        assert entry.entity_id == user.id
        rendered = f"{entry.description} {entry.event_metadata}"
        assert EMPLOYEE_PASSWORD not in rendered
        assert NEW_PASSWORD not in rendered

    async def test_the_response_body_is_empty(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await create_employee(db_session)
        token = await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        response = await change_password(db_client, token)

        assert response.content == b""


class TestOtherSessionsAreRevoked:
    async def test_every_other_session_stops_working(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Changing a password is what you do when you think it leaked."""
        from tests.integration.test_user_management import make_client

        await create_employee(db_session)
        other = await make_client(db_session)
        await log_in(other, email="employee@example.com", password=EMPLOYEE_PASSWORD)
        token = await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        await change_password(db_client, token)

        assert (await other.get("/api/v1/auth/me")).status_code == 401

    async def test_exactly_one_session_is_left_active(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user = await create_employee(db_session)
        token = await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        await change_password(db_client, token)

        sessions = await stored_sessions(db_session, user.id)
        assert len(sessions) == 2
        assert sum(row.revoked_at is None for row in sessions) == 1


class TestRejectedChanges:
    async def test_a_wrong_current_password_is_refused(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await create_employee(db_session)
        token = await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        response = await change_password(db_client, token, current="not-the-password")

        # `422`, not `403`: the caller is already authenticated as this account,
        # so this is a wrong value in the body rather than a refused request.
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "CURRENT_PASSWORD_INVALID"

    async def test_a_wrong_current_password_changes_nothing(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user = await create_employee(db_session)
        token = await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)
        identity = await password_identity(db_session, user.id)
        before = identity.secret_hash

        await change_password(db_client, token, current="not-the-password")

        await db_session.refresh(identity)
        assert identity.secret_hash == before
        assert (await db_client.get("/api/v1/auth/me")).status_code == 200

    async def test_a_new_password_below_the_minimum_length_is_refused(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Caught by the schema bound, before the service is reached at all."""
        await create_employee(db_session)
        token = await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        response = await change_password(db_client, token, new="short")

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    async def test_a_trivial_new_password_is_refused_with_a_reason(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await create_employee(db_session)
        token = await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        response = await change_password(db_client, token, new="passwordpassword")

        assert response.status_code == 422
        body = response.json()["error"]
        assert body["code"] == "PASSWORD_INVALID"
        assert body["details"]

    async def test_reusing_the_current_password_is_refused(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Otherwise a forced rotation could be satisfied with the temporary password."""
        await create_employee(db_session)
        token = await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        response = await change_password(db_client, token, new=EMPLOYEE_PASSWORD)

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "PASSWORD_INVALID"

    async def test_the_rejection_does_not_echo_the_password(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await create_employee(db_session)
        token = await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        response = await change_password(db_client, token, new="hunter2hunter2")

        assert "hunter2hunter2" not in response.text

    async def test_it_needs_a_csrf_token(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await create_employee(db_session)
        await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        response = await db_client.post(
            "/api/v1/auth/password",
            json={"current_password": EMPLOYEE_PASSWORD, "new_password": NEW_PASSWORD},
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "CSRF_TOKEN_INVALID"


class TestForcedRotationGate:
    """ADR-0026: a temporary password unlocks only the three endpoints needed to replace it."""

    async def test_the_flag_is_reported_by_auth_me(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await create_employee(db_session, must_change_password=True)
        await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        response = await db_client.get("/api/v1/auth/me")

        assert response.status_code == 200
        assert response.json()["must_change_password"] is True

    async def test_an_ordinary_endpoint_is_blocked(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await create_employee(db_session, must_change_password=True)
        await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        response = await db_client.get("/api/v1/users/directory")

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"

    async def test_an_admin_holding_a_temporary_password_is_gated_too(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        from tests.support.accounts import ADMIN_PASSWORD, create_admin

        await create_admin(db_session, must_change_password=True)
        await log_in(db_client, email="admin@example.com", password=ADMIN_PASSWORD)

        response = await db_client.get("/api/v1/users")

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"

    async def test_logout_is_still_permitted(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Nobody should be trapped in a session they cannot end."""
        await create_employee(db_session, must_change_password=True)
        token = await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        response = await db_client.post("/api/v1/auth/logout", headers=csrf_headers(token))

        assert response.status_code == 204

    async def test_the_change_endpoint_is_permitted(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await create_employee(db_session, must_change_password=True)
        token = await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        assert (await change_password(db_client, token)).status_code == 204

    async def test_the_gate_lifts_after_the_change(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await create_employee(db_session, must_change_password=True)
        token = await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)
        assert (await db_client.get("/api/v1/users/directory")).status_code == 403

        await change_password(db_client, token)

        assert (await db_client.get("/api/v1/auth/me")).json()["must_change_password"] is False
        assert (await db_client.get("/api/v1/users/directory")).status_code == 200

    async def test_the_operational_probes_are_not_gated(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """They are public, so the gate never applied to them in the first place."""
        await create_employee(db_session, must_change_password=True)
        await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        assert (await db_client.get("/healthz")).status_code == 200
        assert (await db_client.get("/readyz")).status_code == 200
