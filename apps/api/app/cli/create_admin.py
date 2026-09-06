"""Create the first administrator.

    ./scripts/create-admin                            # from the host
    docker compose exec api python -m app.cli.create_admin   # inside the stack

Values are prompted for interactively, or supplied through the environment for
an unattended provisioning step:

    BOOTSTRAP_ADMIN_EMAIL
    BOOTSTRAP_ADMIN_FULL_NAME
    BOOTSTRAP_ADMIN_PASSWORD

There is deliberately **no `--password` flag**. A password on a command line
lands in the shell history, in `ps` output and in any process-monitoring agent
on the box. Interactive entry uses `getpass`, so it is never echoed to the
terminal either.

The command creates exactly one account and refuses to touch an existing one
(`app.services.admin_bootstrap`), so it is safe to re-run.
"""

from __future__ import annotations

import asyncio
import os
import sys
from getpass import getpass
from typing import Final

from app.core.errors import AppError
from app.core.logging import configure_logging
from app.core.settings import get_settings
from app.db.engine import dispose_engine
from app.db.session import get_sessionmaker
from app.services.admin_bootstrap import (
    AdminBootstrapService,
    BootstrapOutcome,
    BootstrapResult,
)

_EMAIL_ENV: Final = "BOOTSTRAP_ADMIN_EMAIL"
_FULL_NAME_ENV: Final = "BOOTSTRAP_ADMIN_FULL_NAME"
_PASSWORD_ENV: Final = "BOOTSTRAP_ADMIN_PASSWORD"  # noqa: S105 - a variable name, not a secret


def _prompt(label: str, env_var: str) -> str:
    """Take a value from the environment, or ask for it."""
    supplied = os.getenv(env_var)
    if supplied:
        return supplied
    if not sys.stdin.isatty():
        raise SystemExit(f"error: {env_var} is not set and there is no terminal to prompt on.")
    return input(f"{label}: ").strip()


def _prompt_password() -> str:
    """Read the password without echoing it, and confirm it when interactive."""
    supplied = os.getenv(_PASSWORD_ENV)
    if supplied:
        return supplied
    if not sys.stdin.isatty():
        raise SystemExit(
            f"error: {_PASSWORD_ENV} is not set and there is no terminal to prompt on."
        )
    password = getpass("Password (not echoed): ")
    if password != getpass("Confirm password: "):
        raise SystemExit("error: the two passwords do not match.")
    return password


async def _create(email: str, full_name: str, password: str) -> BootstrapResult:
    settings = get_settings()
    try:
        async with get_sessionmaker()() as session:
            service = AdminBootstrapService(session, settings)
            return await service.create_initial_admin(
                email=email, full_name=full_name, password=password
            )
    finally:
        await dispose_engine()


def main() -> int:
    """Entry point. Returns a process exit status; never raises for expected refusals."""
    settings = get_settings()
    configure_logging(settings)

    email = _prompt("Email", _EMAIL_ENV)
    full_name = _prompt("Full name", _FULL_NAME_ENV)
    password = _prompt_password()

    try:
        result = asyncio.run(_create(email, full_name, password))
    except AppError as error:
        # The bootstrap refusals — an admin already exists, the password fails
        # the policy — are expected outcomes with useful messages, not
        # tracebacks. `details` carries the policy issue codes.
        sys.stderr.write(f"error: {error.message}\n")
        for detail in error.details:
            sys.stderr.write(f"  - {detail.issue}\n")
        return 1
    except ValueError as error:
        sys.stderr.write(f"error: {error}\n")
        return 1

    if result.outcome is BootstrapOutcome.ALREADY_EXISTS:
        sys.stdout.write(f"{result.email} is already an active administrator. Nothing to do.\n")
        return 0

    sys.stdout.write(
        f"Created administrator {result.email}.\n"
        "Log in at /api/v1/auth/login. Create further accounts through POST /api/v1/users.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
