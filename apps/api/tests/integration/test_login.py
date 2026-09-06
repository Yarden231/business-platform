"""`POST /auth/login` (docs/api.md §5, docs/security.md §2).

The theme of this file is that login must be a *uniform* endpoint: every way of
failing it looks the same from outside, so it cannot be used to discover which
email addresses have accounts.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cookies import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
from app.audit.actions import AuditAction
from app.auth.tokens import hash_token
from app.core.settings import get_settings
from app.models.activity_log import ActivityLog
from app.models.user_identity import UserIdentity
from app.models.user_session import UserSession
from tests.support.accounts import (
    EMPLOYEE_PASSWORD,
    create_employee,
    hours_ago,
    password_identity,
    stored_sessions,
)


async def login(client: AsyncClient, **body: str) -> Response:
    return await client.post("/api/v1/auth/login", json=body)


async def audit_entries(session: AsyncSession) -> list[ActivityLog]:
    rows = await session.scalars(
        select(ActivityLog).order_by(ActivityLog.occurred_at, ActivityLog.id)
    )
    return list(rows)


class TestSuccessfulLogin:
    async def test_it_answers_204_with_no_body(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The session is in the cookie; there is nothing useful to put in a body."""
        await create_employee(db_session)

        response = await login(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        assert response.status_code == 204
        assert response.content == b""

    async def test_it_sets_both_cookies(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await create_employee(db_session)

        await login(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        assert SESSION_COOKIE_NAME in db_client.cookies
        assert CSRF_COOKIE_NAME in db_client.cookies

    async def test_it_persists_a_session_row_for_the_user(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user = await create_employee(db_session)

        await login(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        sessions = await stored_sessions(db_session, user.id)
        assert len(sessions) == 1
        assert sessions[0].revoked_at is None

    async def test_the_email_is_matched_case_insensitively(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Nobody should be locked out of their own account by their mail client."""
        await create_employee(db_session, email="employee@example.com")

        response = await login(db_client, email="EMPLOYEE@Example.COM", password=EMPLOYEE_PASSWORD)

        assert response.status_code == 204

    async def test_surrounding_whitespace_in_the_email_is_ignored(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await create_employee(db_session)

        response = await login(
            db_client, email="  employee@example.com  ", password=EMPLOYEE_PASSWORD
        )

        assert response.status_code == 204

    async def test_the_password_is_not_trimmed(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Whitespace is a legitimate part of a passphrase."""
        await create_employee(db_session)

        response = await login(
            db_client, email="employee@example.com", password=f" {EMPLOYEE_PASSWORD} "
        )

        assert response.status_code == 401

    async def test_a_second_login_issues_a_second_session(
        self, db_client: AsyncClient, db_session: AsyncSession, app: object
    ) -> None:
        """Two browsers are two sessions; logging in on one does not log out the other."""
        user = await create_employee(db_session)

        await login(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)
        db_client.cookies.clear()
        await login(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        sessions = await stored_sessions(db_session, user.id)
        assert len(sessions) == 2
        assert all(row.revoked_at is None for row in sessions)

    async def test_it_records_a_login_audit_event(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user = await create_employee(db_session)

        await login(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        entry = await db_session.scalar(select(ActivityLog))
        assert entry is not None
        assert entry.action == AuditAction.USER_LOGGED_IN.value
        assert entry.actor_user_id == user.id
        assert entry.entity_id == user.id

    async def test_a_previously_failed_attempt_counter_is_reset(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user = await create_employee(db_session)
        await login(db_client, email="employee@example.com", password="wrong-password-here")
        assert (await password_identity(db_session, user.id)).failed_attempt_count == 1

        await login(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        identity = await password_identity(db_session, user.id)
        await db_session.refresh(identity)
        assert identity.failed_attempt_count == 0
        assert identity.locked_until is None

    async def test_it_records_when_the_user_last_logged_in(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user = await create_employee(db_session)
        assert user.last_login_at is None

        await login(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        await db_session.refresh(user)
        assert user.last_login_at is not None


@pytest.mark.usefixtures("_accounts")
class TestUniformFailure:
    """Every rejection is the same status, code and message (docs/security.md §2)."""

    @pytest.fixture
    async def _accounts(self, db_session: AsyncSession) -> None:
        await create_employee(db_session, email="known@example.com")

    @staticmethod
    def shape(response: Response) -> tuple[int, str, str, list[object]]:
        """Everything a caller can see, minus the per-request correlation id."""
        error = response.json()["error"]
        return (
            response.status_code,
            error["code"],
            error["message"],
            error.get("details") or [],
        )

    async def test_an_unknown_email_is_rejected(self, db_client: AsyncClient) -> None:
        response = await login(db_client, email="nobody@example.com", password=EMPLOYEE_PASSWORD)

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "AUTH_INVALID_CREDENTIALS"

    async def test_a_wrong_password_is_rejected_identically(self, db_client: AsyncClient) -> None:
        unknown = await login(db_client, email="nobody@example.com", password=EMPLOYEE_PASSWORD)
        wrong = await login(db_client, email="known@example.com", password="wrong-password")

        assert self.shape(wrong) == self.shape(unknown)

    async def test_a_malformed_address_is_rejected_identically(
        self, db_client: AsyncClient
    ) -> None:
        """A field-level 422 here would say "no account could exist at this address"."""
        unknown = await login(db_client, email="nobody@example.com", password=EMPLOYEE_PASSWORD)
        malformed = await login(db_client, email="not-an-email", password=EMPLOYEE_PASSWORD)

        assert self.shape(malformed) == self.shape(unknown)

    async def test_a_deactivated_account_is_rejected_identically(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """ "Your account is disabled" would confirm the address exists."""
        await create_employee(db_session, email="gone@example.com", deactivated=True)

        unknown = await login(db_client, email="nobody@example.com", password=EMPLOYEE_PASSWORD)
        disabled = await login(db_client, email="gone@example.com", password=EMPLOYEE_PASSWORD)

        assert self.shape(disabled) == self.shape(unknown)

    async def test_a_locked_identity_is_rejected_identically(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """ "Account locked" would be an oracle *and* a denial-of-service report."""
        user = await create_employee(db_session, email="locked@example.com")
        threshold = get_settings().login_max_failed_attempts
        for _ in range(threshold):
            await login(db_client, email="locked@example.com", password="wrong-password")
        assert (await password_identity(db_session, user.id)).locked_until is not None

        locked = await login(db_client, email="locked@example.com", password=EMPLOYEE_PASSWORD)
        unknown = await login(db_client, email="nobody@example.com", password=EMPLOYEE_PASSWORD)

        assert self.shape(locked) == self.shape(unknown)

    async def test_a_user_with_no_password_identity_is_rejected_identically(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A future Entra-only account must not be a password-login oracle."""
        from app.domain.enums import UserRole
        from app.models.user import User

        db_session.add(
            User(email="federated@example.com", full_name="Federated", role=UserRole.EMPLOYEE.value)
        )
        await db_session.flush()

        response = await login(db_client, email="federated@example.com", password=EMPLOYEE_PASSWORD)

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "AUTH_INVALID_CREDENTIALS"

    async def test_no_cookies_are_set_on_failure(self, db_client: AsyncClient) -> None:
        await login(db_client, email="known@example.com", password="wrong-password")

        assert SESSION_COOKIE_NAME not in db_client.cookies
        assert CSRF_COOKIE_NAME not in db_client.cookies

    async def test_no_session_row_is_created_on_failure(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await login(db_client, email="known@example.com", password="wrong-password")

        assert (await db_session.scalar(select(UserSession))) is None

    async def test_the_failure_does_not_echo_the_submitted_password(
        self, db_client: AsyncClient
    ) -> None:
        response = await login(
            db_client, email="known@example.com", password="a-distinctive-secret-42"
        )

        assert "a-distinctive-secret-42" not in response.text


class TestFailureAuditing:
    async def test_a_failure_against_a_known_account_is_attributed_to_it(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user = await create_employee(db_session)

        await login(db_client, email="employee@example.com", password="wrong-password")

        entry = await db_session.scalar(select(ActivityLog))
        assert entry is not None
        assert entry.action == AuditAction.USER_LOGIN_FAILED.value
        assert entry.entity_id == user.id

    async def test_a_failure_against_an_unknown_email_records_no_email(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Otherwise the audit log becomes the enumeration oracle the endpoint is not."""
        await login(db_client, email="nobody@example.com", password="wrong-password")

        entry = await db_session.scalar(select(ActivityLog))
        assert entry is not None
        assert entry.action == AuditAction.USER_LOGIN_FAILED.value
        assert entry.entity_id is None
        assert "nobody@example.com" not in str(entry.event_metadata)
        assert "nobody@example.com" not in entry.description

    async def test_the_failure_event_never_contains_the_password(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await create_employee(db_session)

        await login(db_client, email="employee@example.com", password="a-distinctive-secret-42")

        entry = await db_session.scalar(select(ActivityLog))
        assert entry is not None
        assert "a-distinctive-secret-42" not in str(entry.event_metadata)

    async def test_the_failure_event_records_the_request_context(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """An investigator needs to correlate an attempt with the request log."""
        await create_employee(db_session)

        await login(db_client, email="employee@example.com", password="wrong-password")

        entry = await db_session.scalar(select(ActivityLog))
        assert entry is not None
        assert entry.request_id is not None


class TestLockout:
    async def test_each_failure_increments_the_counter(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user = await create_employee(db_session)

        for expected in (1, 2, 3):
            await login(db_client, email="employee@example.com", password="wrong-password")
            identity = await password_identity(db_session, user.id)
            await db_session.refresh(identity)
            assert identity.failed_attempt_count == expected

    async def test_the_identity_locks_at_the_configured_threshold(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user = await create_employee(db_session)
        threshold = get_settings().login_max_failed_attempts

        for _ in range(threshold - 1):
            await login(db_client, email="employee@example.com", password="wrong-password")
        assert (await password_identity(db_session, user.id)).locked_until is None

        await login(db_client, email="employee@example.com", password="wrong-password")

        identity = await password_identity(db_session, user.id)
        await db_session.refresh(identity)
        assert identity.locked_until is not None

    async def test_the_right_password_is_refused_while_locked(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The whole point: knowing the password later does not undo the lockout."""
        await create_employee(db_session)
        for _ in range(get_settings().login_max_failed_attempts):
            await login(db_client, email="employee@example.com", password="wrong-password")

        response = await login(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        assert response.status_code == 401
        assert SESSION_COOKIE_NAME not in db_client.cookies

    async def test_an_expired_lockout_lets_the_right_password_through(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user = await create_employee(db_session)
        for _ in range(get_settings().login_max_failed_attempts):
            await login(db_client, email="employee@example.com", password="wrong-password")

        identity = await password_identity(db_session, user.id)
        identity.locked_until = hours_ago(1)
        await db_session.flush()

        response = await login(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        assert response.status_code == 204

    async def test_the_attempt_that_locks_the_account_says_so_in_the_audit_log(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """So "when was this locked, and by what" is one row, not a count of failures."""
        await create_employee(db_session)

        for _ in range(get_settings().login_max_failed_attempts):
            await login(db_client, email="employee@example.com", password="wrong-password")

        entries = await audit_entries(db_session)
        assert [entry.event_metadata["lockout_applied"] for entry in entries] == [
            *[False] * (get_settings().login_max_failed_attempts - 1),
            True,
        ]

    async def test_attempts_during_the_cooling_period_do_not_extend_it(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Otherwise an attacker could keep a real user locked out on a schedule."""
        user = await create_employee(db_session)
        for _ in range(get_settings().login_max_failed_attempts):
            await login(db_client, email="employee@example.com", password="wrong-password")
        locked_until = (await password_identity(db_session, user.id)).locked_until

        await login(db_client, email="employee@example.com", password="wrong-password")

        identity = await password_identity(db_session, user.id)
        await db_session.refresh(identity)
        assert identity.locked_until == locked_until

    async def test_the_failure_counter_survives_the_failed_request(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A `401` still has to commit: a rolled-back counter is no counter at all.

        Read straight out of the database with the identity map emptied, so this
        cannot pass on a value that only exists in the session's memory.
        """
        user = await create_employee(db_session)
        user_id = user.id

        await login(db_client, email="employee@example.com", password="wrong-password")

        db_session.expire_all()
        count = await db_session.scalar(
            select(UserIdentity.failed_attempt_count).where(UserIdentity.user_id == user_id)
        )
        assert count == 1


class TestRequestValidation:
    @pytest.mark.parametrize(
        "body",
        [
            {},
            {"email": "employee@example.com"},
            {"password": EMPLOYEE_PASSWORD},
            {"email": "", "password": EMPLOYEE_PASSWORD},
            {"email": "employee@example.com", "password": ""},
        ],
    )
    async def test_a_malformed_body_is_a_validation_error(
        self, db_client: AsyncClient, body: dict[str, str]
    ) -> None:
        response = await db_client.post("/api/v1/auth/login", json=body)

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    async def test_unexpected_fields_are_refused(self, db_client: AsyncClient) -> None:
        """`extra="forbid"`: a typo'd field name should not be silently ignored."""
        response = await db_client.post(
            "/api/v1/auth/login",
            json={
                "email": "employee@example.com",
                "password": EMPLOYEE_PASSWORD,
                "role": "ADMIN",
            },
        )

        assert response.status_code == 422

    async def test_an_oversized_password_is_refused_before_hashing(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """An unbounded password field would be a way to make the server do Argon2 work."""
        await create_employee(db_session)

        response = await db_client.post(
            "/api/v1/auth/login",
            json={"email": "employee@example.com", "password": "x" * 5000},
        )

        assert response.status_code == 422

    async def test_the_validation_error_does_not_echo_the_password(
        self, db_client: AsyncClient
    ) -> None:
        """Pydantic will happily put the input in the error unless it is told not to."""
        response = await db_client.post(
            "/api/v1/auth/login", json={"email": "bad", "password": "a-distinctive-secret-42"}
        )

        assert "a-distinctive-secret-42" not in response.text


class TestSessionStorage:
    async def test_the_cookie_value_is_not_stored_anywhere(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """ADR-0004: a database read must not yield a replayable cookie."""
        user = await create_employee(db_session)

        await login(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        raw = db_client.cookies[SESSION_COOKIE_NAME]
        stored = (await stored_sessions(db_session, user.id))[0]
        assert stored.token_hash != raw
        assert stored.token_hash == hash_token(raw)

    async def test_the_csrf_cookie_value_is_not_stored_either(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user = await create_employee(db_session)

        await login(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        raw = db_client.cookies[CSRF_COOKIE_NAME]
        stored = (await stored_sessions(db_session, user.id))[0]
        assert stored.csrf_token_hash != raw
        assert stored.csrf_token_hash == hash_token(raw)

    async def test_the_session_and_csrf_tokens_are_different_values(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Sharing one value would make the HttpOnly session token readable by script."""
        await create_employee(db_session)

        await login(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        assert db_client.cookies[SESSION_COOKIE_NAME] != db_client.cookies[CSRF_COOKIE_NAME]

    async def test_the_session_records_its_lifetime_from_settings(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user = await create_employee(db_session)

        await login(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        stored = (await stored_sessions(db_session, user.id))[0]
        lifetime = stored.expires_at - stored.issued_at
        assert lifetime.total_seconds() == pytest.approx(
            get_settings().session_absolute_timeout_seconds, abs=2
        )

    async def test_the_session_records_the_client_context(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """So an admin can tell one of their own sessions from an attacker's."""
        user = await create_employee(db_session)

        await db_client.post(
            "/api/v1/auth/login",
            json={"email": "employee@example.com", "password": EMPLOYEE_PASSWORD},
            headers={"User-Agent": "Test Browser/1.0"},
        )

        stored = (await stored_sessions(db_session, user.id))[0]
        assert stored.user_agent == "Test Browser/1.0"
