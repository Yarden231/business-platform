"""Login, logout, session resolution and self-service password change.

This is where the pieces of `app.auth` are composed and where the transaction
boundary sits. Three sequencing decisions here are the difference between a
control that works and one that only looks like it does:

1. **A failed login commits before it raises.** The provider's lockout counter
   is a state change; raising inside `transaction()` would roll it back and hand
   an attacker unlimited guesses. So the failure is recorded and committed, and
   the uniform `401` is raised after the block closes.
2. **The public failure is assembled here, not in the provider.** Unknown email,
   wrong password, lockout and deactivation all become one
   `AUTH_INVALID_CREDENTIALS`, while the audit row keeps the real reason for
   staff (docs/security.md §2).
3. **A password change revokes first and issues second.** Reversing it would
   revoke the session it had just created, logging the user out of the request
   that succeeded.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.actions import AuditAction, AuditEntityType
from app.audit.recorder import AuditRecorder
from app.auth.hashing import get_password_hasher
from app.auth.password_policy import ensure_password_meets_policy
from app.auth.password_provider import PasswordAuthenticationProvider
from app.auth.provider import AuthenticationResult, PasswordCredentials
from app.auth.sessions import USER_AGENT_MAX_LENGTH, IssuedSession, SessionContext, SessionManager
from app.auth.throttle import LoginThrottle
from app.core.errors import CurrentPasswordInvalidError, InvalidCredentialsError
from app.core.settings import Settings
from app.core.time import utc_now
from app.db.uow import transaction
from app.domain.enums import IdentityProvider
from app.repositories.activity_log import ActivityLogRepository
from app.repositories.sessions import SessionRepository
from app.repositories.user_identities import UserIdentityRepository
from app.repositories.users import UserRepository


@dataclass(frozen=True, slots=True)
class RequestOrigin:
    """Where a request came from, for the audit trail.

    Plain values rather than a `Request`, because `app.services` may not import
    the web framework. `user_agent` is client-controlled and truncated on the
    way in.
    """

    ip_address: str | None = None
    user_agent: str | None = None

    def truncated_user_agent(self) -> str | None:
        return self.user_agent[:USER_AGENT_MAX_LENGTH] if self.user_agent else None


class AuthenticationService:
    """Everything under `/api/v1/auth`."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._db = session
        self._settings = settings
        self._users = UserRepository(session)
        self._identities = UserIdentityRepository(session)
        self._audit = AuditRecorder(session)
        self._hasher = get_password_hasher(settings)
        self._sessions = SessionManager(
            sessions=SessionRepository(session),
            users=self._users,
            settings=settings,
        )
        self._provider = PasswordAuthenticationProvider(
            users=self._users,
            identities=self._identities,
            hasher=self._hasher,
            settings=settings,
        )
        self._throttle = LoginThrottle(activity=ActivityLogRepository(session), settings=settings)

    async def login(self, *, email: str, password: str, origin: RequestOrigin) -> IssuedSession:
        """Authenticate and issue a session, or raise the one public failure.

        Raises `TooManyRequestsError` when the source address has exhausted its
        allowance, and `InvalidCredentialsError` for every authentication
        failure whatever its cause.
        """
        await self._throttle.ensure_within_limit(origin.ip_address)

        result = await self._provider.authenticate(
            PasswordCredentials(email=email, password=password)
        )

        if not result.is_success:
            await self._commit_failed_login(result, origin)
            raise InvalidCredentialsError

        assert result.identity is not None  # noqa: S101 - guaranteed by `is_success`

        async with transaction(self._db):
            issued = await self._sessions.issue(
                user_id=result.identity.user_id,
                ip_address=origin.ip_address,
                user_agent=origin.user_agent,
            )
            await self._audit.record(
                action=AuditAction.USER_LOGGED_IN,
                entity_type=AuditEntityType.USER,
                entity_id=result.identity.user_id,
                actor_user_id=result.identity.user_id,
                description="User logged in.",
                metadata={
                    "provider": result.identity.provider.value,
                    "session_id": str(issued.session_id),
                    "user_agent": origin.truncated_user_agent(),
                },
                ip_address=origin.ip_address,
            )
        return issued

    async def logout(self, context: SessionContext, *, origin: RequestOrigin) -> None:
        """Revoke the caller's current session. The cookies are cleared by the router."""
        async with transaction(self._db):
            await self._sessions.revoke(context.session_id)
            await self._audit.record(
                action=AuditAction.USER_LOGGED_OUT,
                entity_type=AuditEntityType.USER,
                entity_id=context.actor.id,
                actor_user_id=context.actor.id,
                description="User logged out.",
                metadata={"session_id": str(context.session_id)},
                ip_address=origin.ip_address,
            )

    async def resolve_session(self, token: str) -> SessionContext:
        """Validate a raw cookie token, refreshing the idle clock when it is due."""
        context = await self._sessions.resolve(token)
        if context.refresh_due:
            async with transaction(self._db):
                await self._sessions.record_use(context.session_id)
        return context

    async def change_own_password(
        self,
        context: SessionContext,
        *,
        current_password: str,
        new_password: str,
        origin: RequestOrigin,
    ) -> IssuedSession:
        """Rotate the caller's own password and hand back a brand-new session.

        The whole use case is one transaction: verify, re-hash, clear
        `must_change_password`, reset the lockout counters, revoke every
        existing session, and record the audit event. A fresh session is issued
        inside the same transaction, so the caller is never left holding a
        cookie that the request they just made has invalidated.
        """
        actor = context.actor
        identity = await self._identities.get_for_user(
            user_id=actor.id, provider=IdentityProvider.PASSWORD
        )
        if identity is None or identity.secret_hash is None:
            # A user with no password identity has no password to change. Not a
            # reachable state in Release 1, and not a `500` if it ever is.
            raise CurrentPasswordInvalidError
        if not self._hasher.verify_password(
            password=current_password, secret_hash=identity.secret_hash
        ):
            raise CurrentPasswordInvalidError

        ensure_password_meets_policy(
            new_password, current_password=current_password, field="new_password"
        )

        user = await self._users.get(actor.id)
        if user is None:  # pragma: no cover - the session resolved a moment ago
            raise CurrentPasswordInvalidError

        async with transaction(self._db):
            now = utc_now()
            identity.secret_hash = self._hasher.hash_password(new_password)
            identity.secret_updated_at = now
            # Rotating the password proves ownership, so any lockout the old
            # one accumulated is spent.
            identity.failed_attempt_count = 0
            identity.locked_until = None
            user.must_change_password = False

            revoked = await self._sessions.revoke_all_for_user(actor.id)
            issued = await self._sessions.issue(
                user_id=actor.id,
                ip_address=origin.ip_address,
                user_agent=origin.user_agent,
            )
            await self._audit.record(
                action=AuditAction.USER_PASSWORD_CHANGED,
                entity_type=AuditEntityType.USER,
                entity_id=actor.id,
                actor_user_id=actor.id,
                description="User changed their own password.",
                metadata={
                    "revoked_session_count": revoked,
                    "session_id": str(issued.session_id),
                },
                ip_address=origin.ip_address,
            )
        return issued

    async def record_csrf_failure(self, context: SessionContext, *, origin: RequestOrigin) -> None:
        """Record a rejected CSRF token (docs/security.md §3).

        Its own transaction, because this runs in a dependency: the request is
        about to fail with a `403`, and the request-scoped session is rolled
        back on the way out. Neither the submitted token nor the session's hash
        is recorded — the event is that verification failed, not what was
        offered.
        """
        async with transaction(self._db):
            await self._audit.record(
                action=AuditAction.CSRF_VALIDATION_FAILED,
                entity_type=AuditEntityType.SESSION,
                entity_id=context.session_id,
                actor_user_id=context.actor.id,
                description="CSRF token verification failed for an authenticated request.",
                metadata={"user_agent": origin.truncated_user_agent()},
                ip_address=origin.ip_address,
            )

    async def _commit_failed_login(
        self, result: AuthenticationResult, origin: RequestOrigin
    ) -> None:
        """Persist the failure counters the provider set, plus the audit row.

        `result.user_id` is `None` when no identity matched, and it stays that
        way: recording the submitted address for a non-existent account would
        turn the audit log into the account-enumeration oracle the login
        endpoint refuses to be (docs/security.md §2). The consequence is
        deliberate and documented — a failed login against an unknown address
        is auditable as an event and by source IP, but not by the address that
        was tried.
        """
        async with transaction(self._db):
            await self._audit.record(
                action=AuditAction.USER_LOGIN_FAILED,
                entity_type=AuditEntityType.USER,
                entity_id=result.user_id,
                actor_user_id=result.user_id,
                description=f"Login failed: {result.outcome.value}.",
                metadata={
                    "outcome": result.outcome.value,
                    "provider": IdentityProvider.PASSWORD.value,
                    "lockout_applied": result.lockout_applied,
                    "user_agent": origin.truncated_user_agent(),
                },
                ip_address=origin.ip_address,
            )
