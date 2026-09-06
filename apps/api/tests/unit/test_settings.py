"""Configuration, and the production start-up guards.

The guards are the point of this module: every value below is a sensible
default on a laptop and an incident in production, and the application refuses
to start with any of them rather than serving traffic and hoping (docs/security.md §9).
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from app.core.settings import (
    DEVELOPMENT_DATABASE_URL,
    DEVELOPMENT_SESSION_SECRET,
    AppEnv,
    LogFormat,
    Settings,
)

PRODUCTION_DATABASE_URL = "postgresql+asyncpg://api:s3cret@db.example.net:5432/cohen?ssl=require"
PRODUCTION_SESSION_SECRET = "x" * 64


def production(**overrides: object) -> Settings:
    """A production configuration that passes every guard, minus the overrides."""
    values: dict[str, object] = {
        "app_env": AppEnv.PRODUCTION,
        "database_url": PRODUCTION_DATABASE_URL,
        "session_secret": PRODUCTION_SESSION_SECRET,
        "cors_allowed_origins": [],
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


class TestDevelopmentDefaults:
    def test_the_repository_starts_with_no_configuration_at_all(self) -> None:
        settings = Settings(database_url=DEVELOPMENT_DATABASE_URL)

        assert settings.app_env is AppEnv.DEVELOPMENT
        assert settings.is_production is False
        assert settings.docs_enabled is True
        assert settings.resolved_log_format is LogFormat.CONSOLE
        assert settings.cors_allowed_origins == ["http://localhost:3000"]

    def test_the_documented_business_defaults_are_the_documented_values(self) -> None:
        settings = Settings(database_url=DEVELOPMENT_DATABASE_URL)

        # docs/domain-model.md §7 and docs/security.md §6 / open question Q9.
        assert settings.case_inactivity_threshold_days == 14
        assert settings.max_upload_size_bytes == 25 * 1024 * 1024
        # docs/open-questions.md Q10: 8 hours idle, 12 hours absolute.
        assert settings.session_idle_timeout_seconds == 8 * 60 * 60
        assert settings.session_absolute_timeout_seconds == 12 * 60 * 60
        # ADR-0007: 64 MiB, t=3, p=4.
        assert settings.argon2_memory_cost == 65536
        assert settings.argon2_time_cost == 3
        assert settings.argon2_parallelism == 4
        # docs/security.md §3: one `last_seen_at` write per minute at most.
        assert settings.session_last_seen_refresh_seconds == 60
        # docs/security.md §2. The per-IP allowance is deliberately looser than
        # the per-identity one: a shared office address is one IP for the firm.
        assert settings.login_max_failed_attempts == 5
        assert settings.login_lockout_seconds == 15 * 60
        assert settings.login_ip_max_failed_attempts == 20
        assert settings.login_ip_window_seconds == 15 * 60

    def test_cookies_are_insecure_in_development_and_secure_in_production(self) -> None:
        """`Secure` is relaxed for plain-HTTP local development only."""
        assert Settings(database_url=DEVELOPMENT_DATABASE_URL).cookies_are_secure is False
        assert production().cookies_are_secure is True

    def test_a_developer_can_opt_into_secure_cookies(self) -> None:
        settings = Settings(database_url=DEVELOPMENT_DATABASE_URL, session_cookie_secure=True)

        assert settings.cookies_are_secure is True


class TestValueValidation:
    def test_a_comma_separated_origin_list_is_accepted(self) -> None:
        settings = Settings(
            database_url=DEVELOPMENT_DATABASE_URL,
            cors_allowed_origins="http://localhost:3000, http://127.0.0.1:3000",  # type: ignore[arg-type]
        )

        assert settings.cors_allowed_origins == ["http://localhost:3000", "http://127.0.0.1:3000"]

    def test_a_wildcard_origin_is_never_allowed(self) -> None:
        with pytest.raises(ValidationError, match="never allowed"):
            Settings(database_url=DEVELOPMENT_DATABASE_URL, cors_allowed_origins=["*"])

    def test_an_origin_must_look_like_an_origin(self) -> None:
        with pytest.raises(ValidationError, match="not an origin"):
            Settings(database_url=DEVELOPMENT_DATABASE_URL, cors_allowed_origins=["localhost:3000"])

    def test_a_synchronous_database_driver_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="asyncpg"):
            Settings(database_url="postgresql://cohen:pw@localhost:5432/cohen_balancing")

    def test_a_short_session_secret_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="at least 32 characters"):
            Settings(database_url=DEVELOPMENT_DATABASE_URL, session_secret=SecretStr("too-short"))

    def test_an_unknown_log_level_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="not a known level"):
            Settings(database_url=DEVELOPMENT_DATABASE_URL, api_log_level="chatty")

    def test_an_absolute_timeout_below_the_idle_timeout_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="never elapse"):
            Settings(
                database_url=DEVELOPMENT_DATABASE_URL,
                session_idle_timeout_seconds=3600,
                session_absolute_timeout_seconds=600,
            )


class TestProductionGuards:
    def test_a_fully_configured_production_environment_starts(self) -> None:
        settings = production()

        assert settings.is_production is True
        assert settings.docs_enabled is False
        assert settings.resolved_log_format is LogFormat.JSON

    def test_the_placeholder_session_secret_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="SESSION_SECRET is still the development"):
            production(session_secret=DEVELOPMENT_SESSION_SECRET)

    def test_the_placeholder_database_url_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="DATABASE_URL is still the development"):
            production(database_url=DEVELOPMENT_DATABASE_URL)

    def test_a_database_url_without_tls_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="must request TLS"):
            production(database_url="postgresql+asyncpg://api:s3cret@db.example.net:5432/cohen")

    def test_a_database_url_that_disables_tls_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="must request TLS"):
            production(
                database_url="postgresql+asyncpg://api:s3cret@db.example.net/cohen?ssl=disable"
            )

    def test_debug_mode_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="DEBUG must be disabled"):
            production(debug=True)

    def test_interactive_documentation_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="API_DOCS_ENABLED must be disabled"):
            production(api_docs_enabled=True)

    def test_sql_echoing_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="DB_ECHO must be disabled"):
            production(db_echo=True)

    def test_insecure_session_cookies_are_refused(self) -> None:
        """Production may not send the session cookie over plain HTTP."""
        with pytest.raises(ValidationError, match="SESSION_COOKIE_SECURE must not be disabled"):
            production(session_cookie_secure=False)

    def test_leaving_cookie_security_to_follow_the_environment_is_fine(self) -> None:
        assert production(session_cookie_secure=None).cookies_are_secure is True

    def test_cross_origin_browser_access_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="CORS_ALLOWED_ORIGINS must be empty"):
            production(cors_allowed_origins=["https://app.example.com"])

    def test_every_problem_is_reported_at_once(self) -> None:
        """A start-up failure should not be a game of whack-a-mole."""
        with pytest.raises(ValidationError) as raised:
            production(debug=True, db_echo=True, session_secret=DEVELOPMENT_SESSION_SECRET)

        message = str(raised.value)
        assert "SESSION_SECRET" in message
        assert "DEBUG" in message
        assert "DB_ECHO" in message


class TestSecrecy:
    def test_the_session_secret_does_not_appear_in_a_repr(self) -> None:
        settings = Settings(
            database_url=DEVELOPMENT_DATABASE_URL,
            session_secret=SecretStr(PRODUCTION_SESSION_SECRET),
        )

        assert PRODUCTION_SESSION_SECRET not in repr(settings)
        assert settings.session_secret.get_secret_value() == PRODUCTION_SESSION_SECRET
