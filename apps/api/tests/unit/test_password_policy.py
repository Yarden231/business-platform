"""The password policy (docs/security.md §2).

Pure domain rules, so these tests need no database, no request and no hashing.
The point of `app.domain.passwords` being importable on its own is that the
policy is provable at its boundaries — one character either side of the minimum
— in milliseconds.
"""

from __future__ import annotations

import pytest

from app.auth.password_policy import ensure_password_meets_policy
from app.core.errors import ErrorCode, PasswordInvalidError
from app.domain.passwords import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    PasswordIssue,
    password_policy_issues,
)


class TestLength:
    def test_the_documented_minimum_is_twelve(self) -> None:
        assert MIN_PASSWORD_LENGTH == 12

    def test_exactly_the_minimum_is_accepted(self) -> None:
        assert password_policy_issues("a" * MIN_PASSWORD_LENGTH) == ()

    def test_one_character_short_is_rejected(self) -> None:
        assert password_policy_issues("a" * (MIN_PASSWORD_LENGTH - 1)) == (PasswordIssue.TOO_SHORT,)

    def test_an_empty_password_is_rejected(self) -> None:
        assert PasswordIssue.TOO_SHORT in password_policy_issues("")

    def test_an_absurdly_long_password_is_rejected(self) -> None:
        """Bounded so a request body cannot make the server do unbounded Argon2 work."""
        assert password_policy_issues("a" * (MAX_PASSWORD_LENGTH + 1)) == (PasswordIssue.TOO_LONG,)

    def test_exactly_the_maximum_is_accepted(self) -> None:
        assert password_policy_issues("a" * MAX_PASSWORD_LENGTH) == ()


class TestNoCompositionRules:
    """Length beats character classes; there are deliberately no class requirements."""

    @pytest.mark.parametrize(
        "password",
        [
            "correct horse battery staple",
            "אבן מפתח סוד ארוך מאוד",
            "all-lower-case-and-fine",
            "1234567890123456",
        ],
    )
    def test_a_long_password_needs_no_uppercase_digit_or_symbol(self, password: str) -> None:
        assert password_policy_issues(password) == ()


class TestDenylist:
    @pytest.mark.parametrize(
        "password",
        ["passwordpassword", "PasswordPassword", "P a s s w o r d Password", "changemenow"],
    )
    def test_an_obvious_value_is_rejected_however_it_is_dressed_up(self, password: str) -> None:
        """Case and punctuation are folded, so the list is not trivially side-stepped."""
        assert PasswordIssue.COMMON in password_policy_issues(password)

    def test_a_denylisted_word_inside_a_longer_passphrase_is_fine(self) -> None:
        """The check is the whole value, not a substring search — that would ban too much."""
        assert password_policy_issues("my password is a secret") == ()


class TestWhitespace:
    def test_whitespace_only_is_rejected_even_when_long_enough(self) -> None:
        issues = password_policy_issues(" " * 20)

        assert PasswordIssue.WHITESPACE_ONLY in issues

    def test_internal_and_surrounding_whitespace_is_otherwise_preserved(self) -> None:
        """Passwords are never trimmed: the characters a user typed are the password."""
        assert password_policy_issues("  a long enough one  ") == ()


class TestReuse:
    def test_the_same_password_again_is_rejected(self) -> None:
        """Otherwise a forced rotation could be satisfied by re-entering the temporary password."""
        issues = password_policy_issues(
            "a-fine-new-password", current_password="a-fine-new-password"
        )

        assert PasswordIssue.SAME_AS_CURRENT in issues

    def test_a_different_password_is_accepted(self) -> None:
        assert password_policy_issues("a-fine-new-password", current_password="the-old-one") == ()

    def test_reuse_is_only_considered_when_the_caller_knows_the_current_password(self) -> None:
        assert password_policy_issues("a-fine-new-password") == ()


class TestEveryProblemIsReportedAtOnce:
    def test_multiple_violations_come_back_together(self) -> None:
        """One round trip should tell a caller everything that is wrong."""
        issues = password_policy_issues("   ")

        assert PasswordIssue.TOO_SHORT in issues
        assert PasswordIssue.WHITESPACE_ONLY in issues


class TestEnforcement:
    def test_an_acceptable_password_raises_nothing(self) -> None:
        ensure_password_meets_policy("a perfectly fine password")

    def test_a_rejected_password_becomes_the_error_envelope(self) -> None:
        with pytest.raises(PasswordInvalidError) as raised:
            ensure_password_meets_policy("short", field="new_password")

        error = raised.value
        assert error.code is ErrorCode.PASSWORD_INVALID
        assert error.status_code == 422
        assert [detail.issue for detail in error.details] == [PasswordIssue.TOO_SHORT.value]
        assert [detail.field for detail in error.details] == ["new_password"]

    def test_the_rejected_password_is_not_in_the_error(self) -> None:
        """docs/security.md §5: a validation error never echoes the value it rejected."""
        with pytest.raises(PasswordInvalidError) as raised:
            ensure_password_meets_policy("hunter2", field="new_password")

        rendered = f"{raised.value.message} {raised.value.details}"
        assert "hunter2" not in rendered
