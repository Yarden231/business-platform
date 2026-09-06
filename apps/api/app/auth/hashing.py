"""Argon2id password hashing (docs/security.md §2).

Argon2id is the memory-hard choice: it resists GPU cracking in a way bcrypt's
4 KiB working set does not, and it is what the OWASP password-storage guidance
recommends first. Parameters come from `Settings`, because they have to be
tuned to the hardware the API actually runs on, and they are recorded *inside*
each hash — Argon2's encoded form is
`$argon2id$v=19$m=65536,t=3,p=4$<salt>$<digest>`. That is what makes
`needs_rehash` possible: raising the cost later is a configuration change plus
a transparent upgrade on each user's next login, not a forced password reset.

Two rules this module exists to keep:

* a plaintext password is an argument and a local, never a field, a log value, a
  return value or an audit payload;
* the only place a hash is persisted is `user_identities.secret_hash`.
"""

from __future__ import annotations

import secrets
from functools import lru_cache

from argon2 import PasswordHasher as Argon2PasswordHasher
from argon2 import Type
from argon2.exceptions import (
    HashingError,
    InvalidHashError,
    VerificationError,
    VerifyMismatchError,
)

from app.core.settings import Settings


class PasswordHasher:
    """Hash and verify passwords with one fixed set of Argon2id parameters."""

    def __init__(self, *, memory_cost: int, time_cost: int, parallelism: int) -> None:
        self._hasher = Argon2PasswordHasher(
            memory_cost=memory_cost,
            time_cost=time_cost,
            parallelism=parallelism,
            type=Type.ID,
        )
        # The enumeration defence below verifies against a real hash of a random
        # value nobody knows. Computed once, here, rather than per login: doing
        # it on every request would hand an attacker a way to make the server do
        # unbounded hashing work, and would be measurably slower than the path
        # it is supposed to be indistinguishable from.
        self._dummy_hash = self._hasher.hash(secrets.token_urlsafe(32))

    def hash_password(self, password: str) -> str:
        """The encoded Argon2id hash of `password`."""
        return self._hasher.hash(password)

    def verify_password(self, *, password: str, secret_hash: str) -> bool:
        """Whether `password` produced `secret_hash`.

        A malformed or unreadable stored hash is a failed verification rather
        than a `500`: a corrupted row must not become an authentication bypass,
        and it must not become an outage for everybody else either.
        """
        try:
            return self._hasher.verify(secret_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    def needs_rehash(self, secret_hash: str) -> bool:
        """Whether `secret_hash` was produced with weaker parameters than the current ones.

        Only ever consulted right after a *successful* verification, which is
        the one moment the plaintext is available to re-hash with.
        """
        try:
            return self._hasher.check_needs_rehash(secret_hash)
        except (InvalidHashError, HashingError):
            # Unreadable by this library: it cannot be upgraded in place, and
            # `verify_password` has already refused it.
            return False

    def verify_dummy(self, password: str) -> None:
        """Spend the same work as a real verification, and discard the answer.

        Called when no identity matches the submitted email, so that "no such
        account" and "wrong password" are not separated by the cost of an
        Argon2 verification (docs/security.md §2). This levels the dominant
        term; it is not a claim of constant time, and the honest limits are
        recorded in `docs/security.md`.

        The outcome is meaningless by construction — the dummy hash is of a
        random value nobody holds — so the mismatch it always raises is
        swallowed here rather than at the call site.
        """
        self.verify_password(password=password, secret_hash=self._dummy_hash)


@lru_cache(maxsize=4)
def _hasher_for(memory_cost: int, time_cost: int, parallelism: int) -> PasswordHasher:
    """One hasher per parameter set, so the dummy hash is computed once per process."""
    return PasswordHasher(memory_cost=memory_cost, time_cost=time_cost, parallelism=parallelism)


def get_password_hasher(settings: Settings) -> PasswordHasher:
    """The process-wide hasher for the configured Argon2 parameters."""
    return _hasher_for(
        settings.argon2_memory_cost,
        settings.argon2_time_cost,
        settings.argon2_parallelism,
    )
