"""Database reachability, for the readiness probe.

Kept here rather than in the router so the HTTP layer never imports SQLAlchemy.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def check_database(session: AsyncSession, *, timeout_seconds: float) -> None:
    """Raise if PostgreSQL cannot answer a trivial query within `timeout_seconds`.

    The timeout matters: an unreachable database that never refuses the
    connection would otherwise hang the probe until the platform's own timeout,
    which reads as "slow" rather than "unavailable".
    """
    await asyncio.wait_for(session.execute(text("SELECT 1")), timeout=timeout_seconds)
