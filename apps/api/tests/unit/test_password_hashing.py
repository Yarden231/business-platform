"""Argon2id hashing (docs/security.md §2).

These tests use cheap parameters so the suite stays fast, and assert the
*wiring* — that the parameters come from `Settings` and end up in the hash —
which is what would break if the production values were ever misconfigured.
The production defaults themselves are asserted in `test_settings.py`.
"""

from __future__ import annotations

import pytest

from app.auth.hashing import PasswordHasher, get_password_hasher
from app.core.settings import DEVELOPMENT_DATABASE_URL, Settings

PASSWORD = "a perfectly reasonable passphrase"


@pytest.fixture
def hasher() -> PasswordHasher:
    return PasswordHasher(memory_cost=8192, time_cost=1, parallelism=1)


class TestHashing:
    def test_it_produces_an_argon2id_hash(self, hasher: PasswordHasher) -> None:
        """Argon2**id**, not `i` or `d`: the hybrid is the OWASP recommendation."""
        assert hasher.hash_password(PASSWORD).startswith("$argon2id$")

    def test_the_hash_does_not_contain_the_password(self, hasher: PasswordHasher) -> None:
        assert PASSWORD not in hasher.hash_password(PASSWORD)

    def test_the_same_password_hashes_differently_every_time(self, hasher: PasswordHasher) -> None:
        """A random salt per hash, so identical passwords are not identifiable as such."""
        assert hasher.hash_password(PASSWORD) != hasher.hash_password(PASSWORD)

    def test_the_parameters_are_recorded_in_the_hash(self, hasher: PasswordHasher) -> None:
        """Self-describing hashes are what make a later parameter increase upgradable."""
        assert "m=8192,t=1,p=1" in hasher.hash_password(PASSWORD)


class TestVerification:
    def test_the_right_password_verifies(self, hasher: PasswordHasher) -> None:
        secret_hash = hasher.hash_password(PASSWORD)

        assert hasher.verify_password(password=PASSWORD, secret_hash=secret_hash) is True

    def test_a_wrong_password_does_not(self, hasher: PasswordHasher) -> None:
        secret_hash = hasher.hash_password(PASSWORD)

        assert hasher.verify_password(password="not it", secret_hash=secret_hash) is False

    def test_verification_is_case_sensitive(self, hasher: PasswordHasher) -> None:
        secret_hash = hasher.hash_password(PASSWORD)

        assert hasher.verify_password(password=PASSWORD.upper(), secret_hash=secret_hash) is False

    @pytest.mark.parametrize("stored", ["", "not-a-hash", "$argon2id$broken", "$2b$12$abc"])
    def test_an_unreadable_stored_hash_fails_closed(
        self, hasher: PasswordHasher, stored: str
    ) -> None:
        """A corrupted row must be a failed login, not an authentication bypass or a 500."""
        assert hasher.verify_password(password=PASSWORD, secret_hash=stored) is False


class TestRehashing:
    def test_a_hash_at_the_current_parameters_needs_no_upgrade(
        self, hasher: PasswordHasher
    ) -> None:
        assert hasher.needs_rehash(hasher.hash_password(PASSWORD)) is False

    def test_a_hash_at_weaker_parameters_needs_one(self) -> None:
        weak = PasswordHasher(memory_cost=8192, time_cost=1, parallelism=1)
        strong = PasswordHasher(memory_cost=16384, time_cost=2, parallelism=1)

        assert strong.needs_rehash(weak.hash_password(PASSWORD)) is True

    def test_an_unreadable_hash_is_not_reported_as_upgradable(self, hasher: PasswordHasher) -> None:
        """It cannot be upgraded in place, and verification has already refused it."""
        assert hasher.needs_rehash("not-a-hash") is False


class TestEnumerationDefence:
    def test_verifying_against_the_dummy_hash_is_silent(self, hasher: PasswordHasher) -> None:
        """It always fails, by construction, so the caller has nothing to handle."""
        hasher.verify_dummy("anything at all")

    def test_the_dummy_hash_is_computed_once_per_hasher(self, hasher: PasswordHasher) -> None:
        """Per-request generation would be a way to make the server do free work."""
        first = hasher._dummy_hash
        hasher.verify_dummy("anything at all")

        assert hasher._dummy_hash == first


class TestSettingsWiring:
    def test_the_hasher_uses_the_configured_parameters(self) -> None:
        settings = Settings(
            database_url=DEVELOPMENT_DATABASE_URL,
            argon2_memory_cost=16384,
            argon2_time_cost=2,
            argon2_parallelism=2,
        )

        secret_hash = get_password_hasher(settings).hash_password(PASSWORD)

        assert "m=16384,t=2,p=2" in secret_hash

    def test_one_hasher_is_shared_per_parameter_set(self) -> None:
        """So the dummy hash is paid for once in the process, not once per login."""
        settings = Settings(
            database_url=DEVELOPMENT_DATABASE_URL,
            argon2_memory_cost=8192,
            argon2_time_cost=1,
            argon2_parallelism=1,
        )

        assert get_password_hasher(settings) is get_password_hasher(settings)
