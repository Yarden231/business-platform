"""Typed application configuration.

One `Settings` object, fed exclusively by environment variables (ADR-0020).
Development defaults are chosen so that `docker compose up` and a bare
`uvicorn app.main:app` both work with no configuration at all; every one of
those defaults is rejected when `APP_ENV=production`, so a production process
cannot inherit a development posture by omission.

`docs/security.md` §9 is the contract this module implements.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Final, Self
from urllib.parse import parse_qsl, urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class AppEnv(StrEnum):
    """Deployment posture. Anything that is not `production` is a developer machine or CI."""

    DEVELOPMENT = "development"
    PRODUCTION = "production"


class LogFormat(StrEnum):
    JSON = "json"
    CONSOLE = "console"


#: The local Compose credentials published in `.env.example`. They exist so the
#: repository starts with one command; production refuses them.
DEVELOPMENT_DATABASE_URL: Final = (
    "postgresql+asyncpg://cohen:local_dev_password@localhost:5432/cohen_balancing"
)
#: A placeholder, not a secret: it is public in this file and in `.env.example`,
#: and `APP_ENV=production` refuses to start with it.
DEVELOPMENT_SESSION_SECRET: Final = "development-only-session-secret-not-for-production"  # noqa: S105

#: Query-string values that mean "the connection is encrypted". asyncpg accepts
#: `ssl=`; `sslmode=` is the libpq spelling and is normalised by SQLAlchemy.
_TLS_ENABLED_VALUES: Final = frozenset({"require", "verify-ca", "verify-full", "true", "on", "1"})
_MIN_SESSION_SECRET_LENGTH: Final = 32


class Settings(BaseSettings):
    """Everything the API reads from its environment."""

    model_config = SettingsConfigDict(
        # Configuration arrives as environment variables in every environment,
        # including production, where the platform injects Key Vault values
        # (ADR-0020). No .env file is read by the application itself.
        env_file=None,
        case_sensitive=False,
        extra="ignore",
    )

    # -- Application ------------------------------------------------------
    app_env: AppEnv = AppEnv.DEVELOPMENT
    debug: bool = False
    #: `None` means "follow APP_ENV". An explicit `true` in production is refused
    #: rather than silently ignored, so the mistake is visible at start-up.
    api_docs_enabled: bool | None = None

    # -- Database ---------------------------------------------------------
    database_url: str = DEVELOPMENT_DATABASE_URL
    db_pool_size: int = Field(default=5, ge=1, le=100)
    db_max_overflow: int = Field(default=5, ge=0, le=100)
    db_pool_recycle_seconds: int = Field(default=1800, ge=1)
    db_connect_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    #: SQLAlchemy statement echoing writes SQL to the logs; never in production.
    db_echo: bool = False

    # -- HTTP -------------------------------------------------------------
    #: Development-only direct browser access to port 8000. The application
    #: itself goes through the same-origin Next.js proxy (ADR-0005), so this is
    #: empty in production and a wildcard is never accepted.
    cors_allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )

    # -- Logging ----------------------------------------------------------
    api_log_level: str = "INFO"
    #: `None` means "follow APP_ENV": readable console output on a developer
    #: machine, JSON everywhere else.
    log_format: LogFormat | None = None

    # -- Sessions ---------------------------------------------------------
    session_secret: SecretStr = SecretStr(DEVELOPMENT_SESSION_SECRET)
    #: Answers to Q10, as configuration rather than literals in the code.
    session_idle_timeout_seconds: int = Field(default=8 * 60 * 60, ge=60)
    session_absolute_timeout_seconds: int = Field(default=12 * 60 * 60, ge=60)
    #: How stale `sessions.last_seen_at` may get before a request refreshes it.
    #: Without this the idle timeout would cost a write on every request
    #: (docs/security.md §3).
    session_last_seen_refresh_seconds: int = Field(default=60, ge=1)
    #: `None` means "follow APP_ENV". Only a plain-HTTP developer machine has a
    #: reason to turn this off, and production refuses to.
    session_cookie_secure: bool | None = None

    # -- Password hashing --------------------------------------------------
    argon2_memory_cost: int = Field(default=65536, ge=8192)
    argon2_time_cost: int = Field(default=3, ge=1)
    argon2_parallelism: int = Field(default=4, ge=1)

    # -- Brute-force protection (docs/security.md §2) ---------------------
    #: Consecutive failures against one identity before it is locked. The
    #: counter lives in `user_identities`, so the control survives a restart and
    #: works across API instances without Redis.
    login_max_failed_attempts: int = Field(default=5, ge=1)
    login_lockout_seconds: int = Field(default=15 * 60, ge=1)
    #: Per-IP throttling, counted from the `USER_LOGIN_FAILED` audit rows of the
    #: trailing window. Higher than the per-identity threshold on purpose: a
    #: shared office NAT address is one IP for the whole firm.
    login_ip_max_failed_attempts: int = Field(default=20, ge=1)
    login_ip_window_seconds: int = Field(default=15 * 60, ge=1)

    # -- Business configuration -------------------------------------------
    #: docs/domain-model.md §7. The number 14 appears exactly once in the
    #: codebase, here, so promoting it to an admin setting later is a change of
    #: source rather than a search-and-replace.
    case_inactivity_threshold_days: int = Field(default=14, ge=1)
    #: Provisional 25 MiB (open question Q9); enforced from Phase 6.
    max_upload_size_bytes: int = Field(default=25 * 1024 * 1024, ge=1)

    # -- Derived ----------------------------------------------------------

    @property
    def is_production(self) -> bool:
        return self.app_env is AppEnv.PRODUCTION

    @property
    def docs_enabled(self) -> bool:
        """Whether FastAPI serves `/docs` and `/openapi.json` (docs/security.md §8)."""
        if self.api_docs_enabled is None:
            return not self.is_production
        return self.api_docs_enabled

    @property
    def cookies_are_secure(self) -> bool:
        """Whether the session and CSRF cookies carry `Secure` (docs/security.md §3)."""
        if self.session_cookie_secure is None:
            return self.is_production
        return self.session_cookie_secure

    @property
    def resolved_log_format(self) -> LogFormat:
        if self.log_format is not None:
            return self.log_format
        return LogFormat.JSON if self.is_production else LogFormat.CONSOLE

    # -- Validation --------------------------------------------------------

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept the comma-separated form every deployment platform produces."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("cors_allowed_origins")
    @classmethod
    def _reject_wildcard_origin(cls, value: list[str]) -> list[str]:
        # Credentialed requests plus `*` is the combination browsers refuse and
        # developers work around; make it impossible by configuration instead.
        if "*" in value:
            raise ValueError(
                "CORS_ALLOWED_ORIGINS must list explicit origins; '*' is never allowed"
            )
        for origin in value:
            if not origin.startswith(("http://", "https://")):
                raise ValueError(f"CORS_ALLOWED_ORIGINS entry is not an origin: {origin!r}")
        return value

    @field_validator("api_log_level")
    @classmethod
    def _known_log_level(cls, value: str) -> str:
        level = value.upper()
        if level not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
            raise ValueError(f"API_LOG_LEVEL is not a known level: {value!r}")
        return level

    @field_validator("database_url")
    @classmethod
    def _async_postgres_driver(cls, value: str) -> str:
        if urlsplit(value).scheme != "postgresql+asyncpg":
            raise ValueError("DATABASE_URL must use the postgresql+asyncpg driver (ADR-0002)")
        return value

    @field_validator("session_secret")
    @classmethod
    def _long_enough_secret(cls, value: SecretStr) -> SecretStr:
        secret = value.get_secret_value()
        if secret != DEVELOPMENT_SESSION_SECRET and len(secret) < _MIN_SESSION_SECRET_LENGTH:
            raise ValueError(
                f"SESSION_SECRET must be at least {_MIN_SESSION_SECRET_LENGTH} characters"
            )
        return value

    @model_validator(mode="after")
    def _absolute_timeout_outlasts_idle_timeout(self) -> Self:
        if self.session_absolute_timeout_seconds < self.session_idle_timeout_seconds:
            raise ValueError(
                "SESSION_ABSOLUTE_TIMEOUT_SECONDS must be at least "
                "SESSION_IDLE_TIMEOUT_SECONDS; otherwise the idle timeout can never elapse"
            )
        return self

    @model_validator(mode="after")
    def _production_is_not_a_developer_machine(self) -> Self:
        """Refuse to start production with a development posture.

        Each of these is a default that is correct on a laptop and a security
        incident in production, so the process fails loudly instead of serving
        traffic with it (docs/security.md §9).
        """
        if not self.is_production:
            return self

        problems: list[str] = []
        if self.session_secret.get_secret_value() == DEVELOPMENT_SESSION_SECRET:
            problems.append("SESSION_SECRET is still the development placeholder")
        if self.debug:
            problems.append("DEBUG must be disabled")
        if self.api_docs_enabled:
            problems.append("API_DOCS_ENABLED must be disabled (docs/security.md §8)")
        if self.db_echo:
            problems.append("DB_ECHO must be disabled; it writes SQL to the logs")
        if self.session_cookie_secure is False:
            problems.append(
                "SESSION_COOKIE_SECURE must not be disabled; it would send the "
                "session cookie over plain HTTP (docs/security.md §3)"
            )
        if self.cors_allowed_origins:
            problems.append(
                "CORS_ALLOWED_ORIGINS must be empty; the browser reaches the API "
                "through the same-origin proxy (ADR-0005)"
            )
        if self.database_url == DEVELOPMENT_DATABASE_URL:
            problems.append("DATABASE_URL is still the development placeholder")
        elif not _database_url_requires_tls(self.database_url):
            problems.append("DATABASE_URL must request TLS (ssl=require or sslmode=require)")

        if problems:
            raise ValueError("Unsafe production configuration: " + "; ".join(problems))
        return self


def _database_url_requires_tls(url: str) -> bool:
    query = dict(parse_qsl(urlsplit(url).query))
    candidates = (query.get("ssl"), query.get("sslmode"))
    return any(value is not None and value.lower() in _TLS_ENABLED_VALUES for value in candidates)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """The process-wide settings object.

    Cached because configuration is immutable for the lifetime of the process;
    tests that need a different environment call `get_settings.cache_clear()`.
    """
    return Settings()
