"""The `AuthenticationProvider` boundary (docs/architecture.md §6).

The abstraction is deliberately one method wide. It answers "who is this?" and
nothing else: it does not issue sessions, set cookies, decide authorization or
write audit rows, because none of those differ between a password login and an
OIDC callback. That is the whole point — `app.auth.sessions`,
`app.auth.policies` and the audit wiring are written once and inherited by every
provider that follows.

What Release 1 needs from it is one implementation,
`PasswordAuthenticationProvider`. What Release 2 needs is an
`EntraIdAuthenticationProvider` whose `Credentials` type is an OIDC
authorization code rather than an email and password. The protocol is generic
over the credential type for exactly that reason, and stops there: there is no
registry, no discovery and no plugin loader, because two providers do not need
one.

### Why this returns a result instead of raising

An authentication *failure* is a state change: it increments
`user_identities.failed_attempt_count` and can set `locked_until`. If the
provider raised, the service's `transaction()` block would roll back — and the
lockout counter would roll back with it, leaving unlimited password guesses.

So the provider reports an outcome, the service commits the counters and the
audit row, and the public `401` is raised *after* the commit. The uniform
response of docs/security.md §2 is the service's job; the provider's job is to
say what actually happened, in enough detail for the audit trail and no more.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.domain.enums import IdentityProvider


class AuthenticationOutcome(StrEnum):
    """What a provider found. Internal: never serialised to a client.

    Every non-`SUCCESS` member becomes the same `401 AUTH_INVALID_CREDENTIALS`
    at the HTTP boundary. The distinctions exist for the audit trail and the
    server log, which only staff can read.
    """

    SUCCESS = "SUCCESS"
    #: No identity matched the submitted login identifier.
    UNKNOWN_IDENTITY = "UNKNOWN_IDENTITY"
    #: The identity exists and the secret was wrong.
    INVALID_SECRET = "INVALID_SECRET"  # noqa: S105 - an outcome name, not a secret
    #: The identity is inside its lockout cooling period.
    LOCKED = "LOCKED"
    #: The credential was correct but the account has been deactivated.
    INACTIVE = "INACTIVE"


@dataclass(frozen=True, slots=True)
class AuthenticatedIdentity:
    """Provider-independent proof of identity, and the input to session issuance.

    It carries no secret and no provider-specific detail, so
    `app.auth.sessions` never has to know which provider produced it.
    """

    user_id: uuid.UUID
    identity_id: uuid.UUID
    provider: IdentityProvider


@dataclass(frozen=True, slots=True)
class AuthenticationResult:
    """The outcome of one authentication attempt."""

    outcome: AuthenticationOutcome
    #: Present only on success.
    identity: AuthenticatedIdentity | None = None
    #: The account the attempt was against, when one was found. `None` for
    #: `UNKNOWN_IDENTITY` — and it stays `None` in the audit row, because an
    #: audit trail that recorded the submitted address for a non-existent
    #: account would become the enumeration oracle the login endpoint refuses
    #: to be (docs/security.md §2).
    user_id: uuid.UUID | None = None
    #: Whether *this* attempt was the one that tripped the lockout. Recorded in
    #: the failure's audit metadata so "when was this account locked, and by
    #: what" is one row rather than a count of preceding failures. A separate
    #: `USER_LOCKED_OUT` action was considered and rejected: the lock and the
    #: failure are the same event, at the same instant, against the same
    #: entity, and splitting them would make the trail harder to read.
    lockout_applied: bool = False

    @property
    def is_success(self) -> bool:
        return self.outcome is AuthenticationOutcome.SUCCESS


@dataclass(frozen=True, slots=True)
class PasswordCredentials:
    """What `POST /api/v1/auth/login` submits.

    A frozen dataclass rather than a Pydantic model because `app.auth` may not
    import `app.schemas`: the HTTP layer validates the body and hands the values
    down, so the CLI can construct the same credentials with no request.
    """

    email: str
    password: str


class AuthenticationProvider[CredentialsT](Protocol):
    """Turns credentials into an identity, or explains why it could not."""

    @property
    def provider(self) -> IdentityProvider:
        """Which `user_identities.provider` this implementation authenticates."""
        ...

    async def authenticate(self, credentials: CredentialsT) -> AuthenticationResult:
        """Verify `credentials`, applying and recording the provider's own failure policy."""
        ...
