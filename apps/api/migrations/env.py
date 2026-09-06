"""Alembic environment, wired to the async engine the application uses.

Migrations live beside `app/` rather than inside it: they import the models to
build `target_metadata`, and `app.db` is not permitted to depend on `app.models`
(docs/architecture.md §4). They are also not application code — they are a
historical record that must keep running unchanged.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from alembic import context
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.logging import configure_logging
from app.core.settings import get_settings

# Importing `app.models` is what populates `Base.metadata`; the import is the
# point, not the name.
from app.models import Base

config = context.config
target_metadata = Base.metadata

# Alembic's template configures logging from alembic.ini here. This project
# uses the application's own pipeline instead, so "which revision ran against
# which database" is a log line of the same shape as everything else — and so
# running a migration in-process, as the test harness does, does not tear down
# the logging the caller already set up.
configure_logging(get_settings())


def _database_url() -> str:
    """Most specific wins: programmatic caller, then `-x db_url=...`, then settings.

    `config.attributes` is how the integration-test harness points a migration
    at the throwaway database it just created, without touching the process's
    environment.
    """
    programmatic = config.attributes.get("db_url")
    if isinstance(programmatic, str):
        return programmatic
    override: str | None = context.get_x_argument(as_dictionary=True).get("db_url")
    return override or get_settings().database_url


def _configure(connection: Connection | None = None, **kwargs: Any) -> None:  # noqa: ANN401
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # Autogenerate must notice a column type change, not only a new column;
        # `scripts/check` fails on any diff between the models and the head.
        compare_type=True,
        # Keeps `alembic check` honest about the pg_trgm extension's own
        # objects, which are not part of the application's metadata.
        include_object=_include_object,
        **kwargs,
    )


def _include_object(
    obj: Any,  # noqa: ANN401 - Alembic passes any schema item
    name: str | None,
    type_: str,
    _reflected: bool,
    _compare_to: Any,  # noqa: ANN401 - Alembic passes any schema item
) -> bool:
    _ = obj
    # pg_trgm installs operator classes and functions, not tables, so nothing
    # needs excluding today. The hook exists so that the first extension that
    # does create a table has an obvious place to be ignored from.
    _ = (name, type_)
    return True


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it — `alembic upgrade head --sql`."""
    _configure(
        url=_database_url(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_migrations(connection: Connection) -> None:
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations(run: Callable[[Connection], None]) -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()
    engine = async_engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(run)
    finally:
        await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(_run_async_migrations(_run_migrations))


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
