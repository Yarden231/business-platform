"""Migrations, exercised end to end on a disposable database.

These tests deliberately do not reuse the shared test database: they need an
empty PostgreSQL instance to upgrade *into*, and they leave nothing behind.

They are synchronous, because Alembic's commands run the async migration
environment with `asyncio.run` and that is only legal outside a running loop.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import make_url

from tests.support.database import (
    alembic_config,
    downgrade_to_base,
    drop_database,
    ensure_database,
    fetch_scalars,
    integration_database_url,
    upgrade_to_head,
)

PHASE_TABLES = {
    "activity_log",
    "alembic_version",
    "people",
    "sessions",
    "user_identities",
    "users",
}


@pytest.fixture
def empty_database() -> Iterator[str]:
    """A database of its own, created empty and dropped afterwards."""
    base = make_url(integration_database_url())
    url = base.set(database=f"migration_probe_{uuid.uuid4().hex[:12]}").render_as_string(
        hide_password=False
    )
    ensure_database(url)
    try:
        yield url
    finally:
        drop_database(url)


def table_names(url: str) -> set[str]:
    return set(fetch_scalars(url, "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))


def test_upgrade_from_an_empty_database_builds_the_whole_schema(empty_database: str) -> None:
    assert table_names(empty_database) == set()

    upgrade_to_head(empty_database)

    assert table_names(empty_database) == PHASE_TABLES
    assert fetch_scalars(empty_database, "SELECT version_num FROM alembic_version") == ["0002"]


def test_downgrade_removes_everything_it_created(empty_database: str) -> None:
    upgrade_to_head(empty_database)

    downgrade_to_base(empty_database)

    # Alembic keeps its own bookkeeping table; nothing of ours survives.
    assert table_names(empty_database) == {"alembic_version"}
    assert (
        fetch_scalars(empty_database, "SELECT extname FROM pg_extension WHERE extname='pg_trgm'")
        == []
    )
    assert (
        fetch_scalars(
            empty_database, "SELECT proname FROM pg_proc WHERE proname='append_only_guard'"
        )
        == []
    )


def test_the_schema_can_be_rebuilt_after_a_downgrade(empty_database: str) -> None:
    """A downgrade that cannot be re-upgraded is a one-way door, not a rollback."""
    upgrade_to_head(empty_database)
    downgrade_to_base(empty_database)
    upgrade_to_head(empty_database)

    assert table_names(empty_database) == PHASE_TABLES


def test_the_models_and_the_migration_head_agree(empty_database: str) -> None:
    """The drift guard: a model change without a migration fails here.

    This is Alembic's own autogenerate comparison, so it covers columns, types,
    nullability, indexes, unique constraints, foreign keys and — on PostgreSQL —
    check constraints. It does not compare triggers, functions or extensions;
    those are asserted directly in `test_schema.py` and
    `test_activity_log_immutability.py`.
    """
    upgrade_to_head(empty_database)

    command.check(alembic_config(empty_database))
