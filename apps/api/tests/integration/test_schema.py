"""What the migrations actually built.

Phase 1 creates the platform and nothing else. This test is the guard against
the schema quietly growing ahead of the roadmap — a table appearing here that
no phase has agreed to is a review conversation, not a merge.
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

PHASE_1_TABLES = {
    "activity_log",
    "alembic_version",
    "sessions",
    "user_identities",
    "users",
}


async def test_only_the_phase_1_tables_exist(db_engine: AsyncEngine) -> None:
    async with db_engine.connect() as connection:
        tables = await connection.run_sync(lambda sync: set(inspect(sync).get_table_names()))

    assert tables == PHASE_1_TABLES


async def test_pg_trgm_is_installed(db_session: AsyncSession) -> None:
    """Hebrew substring search needs it from Phase 4 (ADR-0024); enabling it is privileged."""
    installed = await db_session.scalar(
        text("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
    )

    assert installed == 1


async def test_every_instant_column_is_timezone_aware(db_session: AsyncSession) -> None:
    """ADR-0015: a naive timestamp in this schema would be a silent bug."""
    naive = await db_session.scalars(
        text(
            """
            SELECT table_name || '.' || column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND data_type = 'timestamp without time zone'
            """
        )
    )

    assert list(naive) == []


async def test_every_foreign_key_restricts_deletion(db_session: AsyncSession) -> None:
    """ADR-0011: nothing important is deletable, so a stray DELETE must fail."""
    non_restricting = await db_session.scalars(
        text(
            """
            SELECT conname
            FROM pg_constraint
            WHERE contype = 'f' AND confdeltype <> 'r'
            """
        )
    )

    assert list(non_restricting) == []
