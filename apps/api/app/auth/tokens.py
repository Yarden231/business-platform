"""Session tokens, CSRF tokens and temporary passwords.

Every value here comes from `secrets`, which draws on the OS CSPRNG. `random`
is never used for anything in this module's remit.

Session and CSRF tokens are **hashed, never encrypted**, and the hash is what
the database stores. SHA-256 with no salt or stretching is correct for exactly
this case and wrong for passwords: the input is already 256 bits of uniform
randomness, so there is no guessable plaintext for a dictionary or rainbow
attack to recover. The reason to hash at all is that a database read — a backup,
a `SELECT` by a compromised reporting credential, a leaked dump — must not yield
anything that can be replayed as a cookie (ADR-0004).
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Final

#: 256 bits, as specified for the session cookie in docs/security.md §3.
TOKEN_BYTES: Final = 32

#: A temporary password is read aloud over the phone or typed from a message
#: (ADR-0026), so the alphabet drops the characters that get misheard or
#: mistyped: 0/O, 1/l/I. 20 characters over this 57-character alphabet is about
#: 116 bits of entropy, and the grouping is only there to make it dictatable.
_DICTATABLE_ALPHABET: Final = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
_DICTATABLE_LENGTH: Final = 20
_DICTATABLE_GROUP: Final = 5


def generate_session_token() -> str:
    """A fresh opaque session token. This value goes in the cookie and nowhere else."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def generate_csrf_token() -> str:
    """A fresh CSRF token, bound to one session by the hash stored on its row."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    """The hex SHA-256 of a token — the only form that reaches the database."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_matches(*, token: str, expected_hash: str) -> bool:
    """Whether `token` hashes to `expected_hash`, compared without leaking timing."""
    return secrets.compare_digest(hash_token(token), expected_hash)


def generate_temporary_password() -> str:
    """A one-time password for a newly provisioned or reset account (ADR-0026).

    Returned to the admin exactly once by the API and never stored in plaintext
    anywhere. It comfortably satisfies `app.domain.passwords`, which a unit test
    asserts so the two cannot drift apart.
    """
    characters = [secrets.choice(_DICTATABLE_ALPHABET) for _ in range(_DICTATABLE_LENGTH)]
    groups = [
        "".join(characters[index : index + _DICTATABLE_GROUP])
        for index in range(0, _DICTATABLE_LENGTH, _DICTATABLE_GROUP)
    ]
    return "-".join(groups)
