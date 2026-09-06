"""Issuing, resolving and revoking server-side sessions.

Provider-independent by design: a password login and a future Entra ID callback
both end here, so cookies, CSRF binding, expiry and revocation are written once
(docs/architecture.md §6).

The invariant this module exists to hold: **the raw session token and the raw
CSRF token exist only in the return value of `issue`, on their way to two
`Set-Cookie` headers.** Nothing else in the codebase can obtain either one —
the database holds SHA-256 hashes, and `SessionContext` deliberately offers a
comparison method rather than an accessor.

Nothing here commits; the calling service owns the transaction.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from app.auth.tokens import (
    generate_csrf_token,
    generate_session_token,
    hash_token,
    token_matches,
)
from app.core.errors import (
    AccountInactiveError,
    AuthenticationRequiredError,
    SessionExpiredError,
)
from app.core.settings import Settings
from app.core.time import utc_now
from app.domain.actor import AuthenticatedActor
from app.domain.enums import UserRole
from app.domain.sessions import last_seen_refresh_is_due, session_invalidity
from app.models.user_session import UserSession
from app.repositories.sessions import SessionRepository
from app.repositories.users import UserRepository

#: `sessions.user_agent` is a client-controlled string of unbounded length.
#: Stored because it is useful when reviewing an authentication event, truncated
#: because it is not worth an unbounded column.
USER_AGENT_MAX_LENGTH: Final = 400


@dataclass(frozen=True, slots=True)
class IssuedSession:
    """A freshly created session, and the only place its raw tokens appear.

    The caller's single legitimate use for `token` and `csrf_token` is to write
    them into cookies. They are never logged, audited, persisted or returned in
    a response body.
    """

    session_id: uuid.UUID
    token: str
    csrf_token: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class SessionContext:
    """A validated session and the actor it belongs to.

    `csrf_token_hash` is carried so that the CSRF check costs no second query,
    and it is compared through `csrf_token_matches` rather than read: the HTTP
    layer never needs the value, and a method is harder to accidentally
    serialise than a field.
    """

    actor: AuthenticatedActor
    session_id: uuid.UUID
    csrf_token_hash: str
    #: Whether `last_seen_at` is stale enough that this request should refresh it.
    refresh_due: bool

    def csrf_token_matches(self, token: str) -> bool:
        """Whether `token` is the CSRF token bound to *this* session.

        This is the part a bare double-submit check gets wrong: comparing a
        cookie to a header proves only that the sender could set both, which an
        attacker who can write cookies can. Comparing against the hash on the
        session row proves the token was issued with this session
        (docs/security.md §3).
        """
        return token_matches(token=token, expected_hash=self.csrf_token_hash)


class SessionManager:
    """The session store: create, validate, revoke."""

    def __init__(
        self,
        *,
        sessions: SessionRepository,
        users: UserRepository,
        settings: Settings,
    ) -> None:
        self._sessions = sessions
        self._users = users
        self._settings = settings

    async def issue(
        self,
        *,
        user_id: uuid.UUID,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> IssuedSession:
        """Create a session row and return its raw tokens.

        Called on every successful authentication and again after a password
        change, which is what prevents session fixation: a session identifier
        that existed before the credential was proven is never carried forward
        (docs/security.md §3).
        """
        now = utc_now()
        token = generate_session_token()
        csrf_token = generate_csrf_token()
        expires_at = now + timedelta(seconds=self._settings.session_absolute_timeout_seconds)

        user_session = UserSession(
            user_id=user_id,
            token_hash=hash_token(token),
            csrf_token_hash=hash_token(csrf_token),
            issued_at=now,
            last_seen_at=now,
            expires_at=expires_at,
            user_agent=user_agent[:USER_AGENT_MAX_LENGTH] if user_agent else None,
            ip_address=ip_address,
        )
        self._sessions.add(user_session)

        return IssuedSession(
            session_id=user_session.id,
            token=token,
            csrf_token=csrf_token,
            expires_at=expires_at,
        )

    async def resolve(self, token: str) -> SessionContext:
        """Validate a raw cookie token and return the actor it authenticates.

        Raises rather than returning `None` because every caller's next step
        would be to raise anyway, and because the distinction between "no such
        session", "expired" and "deactivated" is worth preserving for the
        client — none of it discloses anything the holder of the cookie does not
        already know.
        """
        user_session = await self._sessions.get_by_token_hash(hash_token(token))
        if user_session is None:
            # Indistinguishable from a forged or truncated cookie, and treated
            # the same way: there is nothing to expire.
            raise AuthenticationRequiredError

        now = utc_now()
        invalidity = session_invalidity(
            last_seen_at=user_session.last_seen_at,
            expires_at=user_session.expires_at,
            revoked_at=user_session.revoked_at,
            now=now,
            idle_timeout_seconds=self._settings.session_idle_timeout_seconds,
        )
        if invalidity is not None:
            raise SessionExpiredError

        user = await self._users.get(user_session.user_id)
        if user is None or user.deactivated_at is not None:
            # Deactivation revokes sessions in the same transaction, so this is
            # defence in depth rather than the primary control — and it is what
            # makes a session that somehow outlived its revocation useless.
            raise AccountInactiveError

        return SessionContext(
            actor=AuthenticatedActor(
                id=user.id,
                email=user.email,
                full_name=user.full_name,
                role=UserRole(user.role),
                must_change_password=user.must_change_password,
            ),
            session_id=user_session.id,
            csrf_token_hash=user_session.csrf_token_hash,
            refresh_due=last_seen_refresh_is_due(
                last_seen_at=user_session.last_seen_at,
                now=now,
                refresh_interval_seconds=self._settings.session_last_seen_refresh_seconds,
            ),
        )

    async def record_use(self, session_id: uuid.UUID) -> None:
        """Push the idle clock forward. Write-throttled by `resolve`'s `refresh_due`."""
        user_session = await self._sessions.get(session_id)
        if user_session is not None:
            await self._sessions.touch(user_session, at=utc_now())

    async def revoke(self, session_id: uuid.UUID) -> None:
        """Revoke one session — logout's half of the work."""
        user_session = await self._sessions.get(session_id)
        if user_session is not None and user_session.revoked_at is None:
            await self._sessions.revoke(user_session, at=utc_now())

    async def revoke_all_for_user(
        self, user_id: uuid.UUID, *, excluding: uuid.UUID | None = None
    ) -> int:
        """Revoke every live session of a user; returns how many.

        The count is recorded in the audit metadata of the action that caused
        it, which is how "was anybody actually signed out?" is answered later.
        """
        return await self._sessions.revoke_all_for_user(user_id, at=utc_now(), excluding=excluding)
