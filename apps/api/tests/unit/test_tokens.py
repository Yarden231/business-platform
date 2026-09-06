"""Session tokens, CSRF tokens and temporary passwords (docs/security.md §3, ADR-0026)."""

from __future__ import annotations

import hashlib
import string

from app.auth.tokens import (
    TOKEN_BYTES,
    generate_csrf_token,
    generate_session_token,
    generate_temporary_password,
    hash_token,
    token_matches,
)
from app.domain.passwords import password_policy_issues


class TestSessionTokens:
    def test_the_token_carries_the_documented_entropy(self) -> None:
        assert TOKEN_BYTES == 32  # 256 bits, per docs/security.md §3.

        # url-safe base64 of 32 bytes, unpadded.
        assert len(generate_session_token()) >= 43

    def test_every_token_is_different(self) -> None:
        assert len({generate_session_token() for _ in range(100)}) == 100

    def test_the_token_survives_a_cookie_header_unencoded(self) -> None:
        """url-safe base64 needs no escaping, so what is set is what comes back."""
        allowed = set(string.ascii_letters + string.digits + "-_")

        assert set(generate_session_token()) <= allowed

    def test_a_csrf_token_is_generated_the_same_way_and_is_distinct(self) -> None:
        assert len({generate_csrf_token() for _ in range(100)}) == 100
        assert generate_csrf_token() != generate_session_token()


class TestHashing:
    def test_the_stored_form_is_a_hex_sha256(self) -> None:
        token = generate_session_token()

        digest = hash_token(token)

        assert digest == hashlib.sha256(token.encode()).hexdigest()
        assert len(digest) == 64
        assert set(digest) <= set(string.hexdigits.lower())

    def test_the_hash_does_not_contain_the_token(self) -> None:
        """A database read must not yield anything replayable as a cookie (ADR-0004)."""
        token = generate_session_token()

        assert token not in hash_token(token)

    def test_hashing_is_deterministic(self) -> None:
        """It has to be: the cookie is looked up by its hash on every request."""
        token = generate_session_token()

        assert hash_token(token) == hash_token(token)

    def test_different_tokens_hash_differently(self) -> None:
        assert hash_token("a") != hash_token("b")


class TestComparison:
    def test_the_right_token_matches_its_hash(self) -> None:
        token = generate_session_token()

        assert token_matches(token=token, expected_hash=hash_token(token)) is True

    def test_a_wrong_token_does_not(self) -> None:
        assert token_matches(token="wrong", expected_hash=hash_token("right")) is False

    def test_an_empty_token_does_not_match_an_empty_stored_hash(self) -> None:
        """Fail closed if a row were ever written with no CSRF hash at all."""
        assert token_matches(token="", expected_hash="") is False


class TestTemporaryPasswords:
    def test_it_satisfies_the_password_policy(self) -> None:
        """Otherwise provisioning would hand out a password the change endpoint rejects."""
        for _ in range(20):
            assert password_policy_issues(generate_temporary_password()) == ()

    def test_every_temporary_password_is_different(self) -> None:
        assert len({generate_temporary_password() for _ in range(100)}) == 100

    def test_it_is_grouped_for_dictating_over_the_phone(self) -> None:
        password = generate_temporary_password()

        assert len(password.split("-")) == 4
        assert all(len(group) == 5 for group in password.split("-"))

    def test_it_avoids_the_characters_that_get_misheard(self) -> None:
        """No 0/O and no 1/l/I, because these are read aloud (ADR-0026)."""
        confusable = set("0O1lI")

        for _ in range(50):
            assert not confusable & set(generate_temporary_password())
