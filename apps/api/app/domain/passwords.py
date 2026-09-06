"""The password policy (docs/security.md §2).

Length beats character-class rules, so there are no composition requirements
here: no mandatory uppercase, digit or symbol. Those rules push people towards
`Password1!` and buy very little, and NIST SP 800-63B recommends against them.
What this module enforces is a floor on length and a refusal of the handful of
values that are guessed first.

The module is pure — no FastAPI, no SQLAlchemy, no settings — so the policy is
unit-tested directly and is identical whether it is applied by an HTTP request,
the admin bootstrap CLI or a future scheduled job.

It returns codes rather than sentences. The API turns them into `details`
entries and the web app maps them to Hebrew (ADR-0014), and no layer in between
has to agree on English wording.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

#: docs/security.md §2. Twelve characters is the documented floor.
MIN_PASSWORD_LENGTH: Final = 12
#: Argon2 has no practical input ceiling, but an unbounded body is a cheap way
#: to make the server do 64 MiB of hashing work per request, so the request is
#: rejected before it reaches the hasher.
MAX_PASSWORD_LENGTH: Final = 256


class PasswordIssue(StrEnum):
    """Stable, machine-readable policy violations."""

    TOO_SHORT = "too_short"
    TOO_LONG = "too_long"
    COMMON = "common"
    WHITESPACE_ONLY = "whitespace_only"
    #: Only reachable when the caller supplies the current password, which the
    #: self-service change endpoint has already verified. Without this rule a
    #: user forced to rotate a temporary password could "change" it to itself
    #: and clear `must_change_password` while still holding the credential an
    #: admin read out over the phone (ADR-0026).
    SAME_AS_CURRENT = "same_as_current"


#: Deliberately small. A real breach-corpus check (Have I Been Pwned's k-anonymity
#: range API) is the right long-term control and is an outbound HTTP dependency
#: this release does not have; a list of thousands of entries compiled into the
#: repository would be the appearance of that control without its value. These
#: are the values that appear at the top of every leaked-password list, plus the
#: ones this project's own documentation makes obvious.
_DENYLIST: Final = frozenset(
    {
        "administrator",
        "changeme",
        "changemenow",
        "cohenbalancing",
        "letmein12345",
        "password",
        "password1234",
        "passwordpassword",
        "qwertyuiop123",
        "temporarypassword",
        "welcome12345",
    }
)


def password_policy_issues(
    password: str, *, current_password: str | None = None
) -> tuple[PasswordIssue, ...]:
    """Every way `password` fails the policy; empty means it is acceptable.

    All violations are reported at once rather than the first one, so a caller
    fixing a password is told everything that is wrong with it in one round
    trip. `current_password` is supplied only by the self-service change flow,
    which is the only caller that knows it.
    """
    issues: list[PasswordIssue] = []

    if len(password) < MIN_PASSWORD_LENGTH:
        issues.append(PasswordIssue.TOO_SHORT)
    if len(password) > MAX_PASSWORD_LENGTH:
        issues.append(PasswordIssue.TOO_LONG)
    if password and not password.strip():
        issues.append(PasswordIssue.WHITESPACE_ONLY)
    if _normalise(password) in _DENYLIST:
        issues.append(PasswordIssue.COMMON)
    if current_password is not None and password == current_password:
        issues.append(PasswordIssue.SAME_AS_CURRENT)

    return tuple(issues)


def _normalise(password: str) -> str:
    """Fold the variations that make a denylist trivial to walk around.

    `Password!`, `P a s s w o r d` and `password` are the same guess, so the
    comparison is case-insensitive and ignores anything that is not a letter or
    a digit. The password itself is never stored or logged in either form.
    """
    return "".join(character for character in password.lower() if character.isalnum())
