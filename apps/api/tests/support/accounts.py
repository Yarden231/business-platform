"""Building accounts and sessions for the authentication tests.

Deliberately *not* a factory layer — Phase 4 introduces those with `people`,
the first entity with enough optional fields to warrant one. These are the two
or three things every authentication test needs, written once so a test body
says what it is testing rather than how it set itself up.

`create_password_user` goes through the real hasher rather than inserting a
canned hash, so a test that logs in is exercising the same verification path
production does.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cookies import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, SESSION_COOKIE_NAME
from app.auth.hashing import get_password_hasher
from app.core.settings import get_settings
from app.core.time import utc_now
from app.domain.enums import IdentityProvider, UserRole
from app.models.user import User
from app.models.user_identity import UserIdentity
from app.models.user_session import UserSession

#: Fake, obviously-local credentials. Long enough to satisfy the password
#: policy, and they exist nowhere but in this test suite.
ADMIN_PASSWORD = "admin-development-passphrase"
EMPLOYEE_PASSWORD = "employee-development-passphrase"


async def create_password_user(
    session: AsyncSession,
    *,
    email: str,
    full_name: str = "Test Person",
    role: UserRole = UserRole.EMPLOYEE,
    password: str,
    must_change_password: bool = False,
    deactivated: bool = False,
) -> User:
    """A user plus the `PASSWORD` identity that lets them log in."""
    hasher = get_password_hasher(get_settings())
    user = User(
        email=email.strip().lower(),
        full_name=full_name,
        role=role.value,
        must_change_password=must_change_password,
        deactivated_at=utc_now() if deactivated else None,
    )
    identity = UserIdentity(
        user_id=user.id,
        provider=IdentityProvider.PASSWORD.value,
        provider_subject=user.email,
        secret_hash=hasher.hash_password(password),
        secret_updated_at=utc_now(),
    )
    session.add(user)
    session.add(identity)
    await session.flush()
    return user


async def create_admin(
    session: AsyncSession, *, email: str = "admin@example.com", **kwargs: object
) -> User:
    return await create_password_user(
        session,
        email=email,
        full_name="Admin Person",
        role=UserRole.ADMIN,
        password=ADMIN_PASSWORD,
        **kwargs,  # type: ignore[arg-type]
    )


async def create_employee(
    session: AsyncSession, *, email: str = "employee@example.com", **kwargs: object
) -> User:
    return await create_password_user(
        session,
        email=email,
        full_name="Employee Person",
        role=UserRole.EMPLOYEE,
        password=EMPLOYEE_PASSWORD,
        **kwargs,  # type: ignore[arg-type]
    )


async def log_in(client: AsyncClient, *, email: str, password: str) -> str:
    """Log `client` in and return the CSRF token it must echo on unsafe methods.

    The session cookie is kept by the client's own cookie jar, exactly as a
    browser would keep it, so a test never handles the token itself.
    """
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 204, response.text
    return client.cookies[CSRF_COOKIE_NAME]


def csrf_headers(token: str) -> dict[str, str]:
    return {CSRF_HEADER_NAME: token}


def session_cookie(client: AsyncClient) -> str:
    return client.cookies[SESSION_COOKIE_NAME]


async def stored_sessions(session: AsyncSession, user_id: uuid.UUID) -> list[UserSession]:
    """Every session row of a user, newest first."""
    rows = await session.scalars(
        select(UserSession)
        .where(UserSession.user_id == user_id)
        .order_by(UserSession.issued_at.desc())
    )
    return list(rows)


async def password_identity(session: AsyncSession, user_id: uuid.UUID) -> UserIdentity:
    identity = await session.scalar(
        select(UserIdentity).where(
            UserIdentity.user_id == user_id,
            UserIdentity.provider == IdentityProvider.PASSWORD.value,
        )
    )
    assert identity is not None
    return identity


async def age_session(
    session: AsyncSession,
    user_session: UserSession,
    *,
    last_seen: datetime | None = None,
    expires: datetime | None = None,
) -> None:
    """Move a session's clocks into the past.

    Backdating the row is how expiry is tested: the alternative is waiting out
    an eight-hour idle timeout, and monkeypatching the clock would test the
    patch rather than the rule. The rule itself is unit tested directly against
    `app.domain.sessions`.

    `issued_at` is dragged back with `expires_at` when it has to be, because
    `ck_sessions_expires_after_issued` will not accept a session that expired
    before it was issued — which is the database refusing to hold a row that
    could never have existed, and worth keeping.
    """
    if last_seen is not None:
        user_session.last_seen_at = last_seen
    if expires is not None:
        user_session.expires_at = expires
        if user_session.issued_at >= expires:
            user_session.issued_at = expires - timedelta(hours=12)
    await session.flush()


def hours_ago(hours: float) -> datetime:
    return utc_now() - timedelta(hours=hours)
