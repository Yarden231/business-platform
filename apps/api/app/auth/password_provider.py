"""Email + password authentication (docs/security.md §2).

This is the Release 1 implementation of `AuthenticationProvider`. It owns the
per-identity brute-force policy, because a lockout counter is a property of a
credential rather than of a person — which is also why the columns live on
`user_identities` and not on `users` (ADR-0006).

Three behaviours are load-bearing and easy to lose in a refactor:

1. **The password is always verified**, even when no identity matched, against a
   dummy hash computed once per process. Skipping the work when the account does
   not exist is what turns a login endpoint into a user-enumeration oracle
   measurable with a stopwatch.
2. **An active lockout does not extend itself.** Attempts made during the
   cooling period are refused without touching the counter, so an attacker
   cannot keep a real user locked out indefinitely by guessing on a schedule.
3. **Counter mutations are flushed, not committed.** The service's transaction
   commits them even though the request ends in a `401`, which is the only
   reason the lockout survives at all.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.auth.hashing import PasswordHasher
from app.auth.provider import (
    AuthenticatedIdentity,
    AuthenticationOutcome,
    AuthenticationResult,
    PasswordCredentials,
)
from app.core.settings import Settings
from app.core.time import utc_now
from app.domain.enums import IdentityProvider
from app.models.user_identity import UserIdentity
from app.repositories.user_identities import UserIdentityRepository
from app.repositories.users import UserRepository, normalize_email


class PasswordAuthenticationProvider:
    """Verifies a password against a `PASSWORD` identity's Argon2id hash."""

    def __init__(
        self,
        *,
        users: UserRepository,
        identities: UserIdentityRepository,
        hasher: PasswordHasher,
        settings: Settings,
    ) -> None:
        self._users = users
        self._identities = identities
        self._hasher = hasher
        self._settings = settings

    @property
    def provider(self) -> IdentityProvider:
        return IdentityProvider.PASSWORD

    async def authenticate(self, credentials: PasswordCredentials) -> AuthenticationResult:
        identity = await self._identities.get_by_subject(
            provider=IdentityProvider.PASSWORD,
            subject=normalize_email(credentials.email),
        )

        if identity is None or identity.secret_hash is None:
            self._hasher.verify_dummy(credentials.password)
            return AuthenticationResult(outcome=AuthenticationOutcome.UNKNOWN_IDENTITY)

        verified = self._hasher.verify_password(
            password=credentials.password, secret_hash=identity.secret_hash
        )
        now = utc_now()

        if identity.locked_until is not None and identity.locked_until > now:
            return AuthenticationResult(
                outcome=AuthenticationOutcome.LOCKED, user_id=identity.user_id
            )

        if not verified:
            locked = await self._register_failure(identity, now=now)
            return AuthenticationResult(
                outcome=AuthenticationOutcome.INVALID_SECRET,
                user_id=identity.user_id,
                lockout_applied=locked,
            )

        user = await self._users.get(identity.user_id)
        if user is None or user.deactivated_at is not None:
            # The credential was right, so there is nothing to count: this is a
            # closed account, not an attack. The public response is still the
            # same 401.
            return AuthenticationResult(
                outcome=AuthenticationOutcome.INACTIVE, user_id=identity.user_id
            )

        identity.failed_attempt_count = 0
        identity.locked_until = None
        # The plaintext is in hand exactly here, which is the only moment a hash
        # produced under weaker parameters can be upgraded without asking the
        # user for anything (docs/security.md §2).
        if self._hasher.needs_rehash(identity.secret_hash):
            identity.secret_hash = self._hasher.hash_password(credentials.password)
        user.last_login_at = now

        return AuthenticationResult(
            outcome=AuthenticationOutcome.SUCCESS,
            user_id=user.id,
            identity=AuthenticatedIdentity(
                user_id=user.id,
                identity_id=identity.id,
                provider=IdentityProvider.PASSWORD,
            ),
        )

    async def _register_failure(self, identity: UserIdentity, *, now: datetime) -> bool:
        """Count one failed attempt, and lock the identity once the threshold is reached.

        Returns whether this attempt was the one that applied the lock, which
        the service records in the audit trail.

        An expired lockout resets the count rather than accumulating on top of
        it: the cooling period has already served its purpose, and carrying the
        old failures forward would lock a user who mistypes once more after
        waiting it out.
        """
        expired_lockout = identity.locked_until is not None and identity.locked_until <= now
        previous = 0 if expired_lockout else identity.failed_attempt_count

        identity.failed_attempt_count = previous + 1
        identity.locked_until = None

        if identity.failed_attempt_count >= self._settings.login_max_failed_attempts:
            identity.locked_until = now + timedelta(seconds=self._settings.login_lockout_seconds)
            return True
        return False
