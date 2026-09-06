"""Test-database plumbing.

Integration tests run against real PostgreSQL, never SQLite (ADR-0022). The
invariants that carry this system — partial unique indexes, check constraints,
composite foreign keys, the append-only trigger — have no SQLite equivalent, so
a substitute engine would test a schema that is not the one we deploy.

The schema is always built by `alembic upgrade head`, never by
`Base.metadata.create_all()`. That way every test run exercises the migrations,
and a migration that works only on an empty models file fails immediately
instead of on the day it is deployed.
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Any, Final

from alembic import command
from alembic.config import Config
from sqlalchemy import make_url, text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.settings import get_settings

API_ROOT: Final = Path(__file__).resolve().parents[2]
#: PostgreSQL always has this database, so it is where `CREATE DATABASE` runs from.
_MAINTENANCE_DATABASE: Final = "postgres"
_SAFE_DATABASE_NAME: Final = re.compile(r"^[A-Za-z0-9_]+$")


def integration_database_url() -> str:
    """Where integration tests connect.

    `TEST_DATABASE_URL` wins. Otherwise the application's own `DATABASE_URL` is
    reused with `_test` appended to the database name, so a developer who
    changed a port or a password in `.env` does not have to change a second
    variable — and so a test run can never write to the development database by
    accident.
    """
    configured = os.getenv("TEST_DATABASE_URL")
    if configured:
        return configured
    url = make_url(get_settings().database_url)
    return url.set(database=f"{url.database}_test").render_as_string(hide_password=False)


def alembic_config(url: str) -> Config:
    """An Alembic configuration pointed at `url`, wherever the tests run from."""
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.attributes["db_url"] = url
    return config


def ensure_database(url: str) -> None:
    """Create the database if it is not there yet. Safe to call repeatedly."""
    asyncio.run(_ensure_database(make_url(url)))


def drop_database(url: str) -> None:
    """Delete a database, disconnecting anything still attached to it."""
    asyncio.run(_drop_database(make_url(url)))


def upgrade_to_head(url: str) -> None:
    command.upgrade(alembic_config(url), "head")


def downgrade_to_base(url: str) -> None:
    command.downgrade(alembic_config(url), "base")


def fetch_scalars(url: str, query: str) -> list[Any]:
    """Run a read-only query outside the async harness, for the migration tests."""
    return asyncio.run(_fetch_scalars(url, query))


async def _fetch_scalars(url: str, query: str) -> list[Any]:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            return list(await connection.scalars(text(query)))
    finally:
        await engine.dispose()


async def _ensure_database(url: URL) -> None:
    name = _database_name(url)
    engine = create_async_engine(
        url.set(database=_MAINTENANCE_DATABASE),
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
    )
    try:
        async with engine.connect() as connection:
            exists = await connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name}
            )
            if not exists:
                # A database name cannot be a bound parameter. It comes from our
                # own configuration and is checked against `_SAFE_DATABASE_NAME`
                # in `_database_name` before it gets here.
                await connection.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        await engine.dispose()


async def _drop_database(url: URL) -> None:
    name = _database_name(url)
    engine = create_async_engine(
        url.set(database=_MAINTENANCE_DATABASE),
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
    )
    try:
        async with engine.connect() as connection:
            await connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    finally:
        await engine.dispose()


def _database_name(url: URL) -> str:
    name = url.database
    if not name or not _SAFE_DATABASE_NAME.match(name):
        raise ValueError(f"Refusing to manage a database with this name: {name!r}")
    return name
