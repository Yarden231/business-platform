"""Reads and writes over `sessions`.

Lookup is always by token *hash*: the raw cookie value is hashed by the caller
and the hash is what this module matches against the unique index. There is no
method here that accepts a raw token, so no query in the system can be written
that would need one.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_session import UserSession


class SessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, user_session: UserSession) -> None:
        self._session.add(user_session)

    async def get_by_token_hash(self, token_hash: str) -> UserSession | None:
        """One indexed lookup on `UNIQUE (token_hash)` — the per-request cost of ADR-0004."""
        found: UserSession | None = await self._session.scalar(
            select(UserSession).where(UserSession.token_hash == token_hash)
        )
        return found

    async def get(self, session_id: uuid.UUID) -> UserSession | None:
        return await self._session.get(UserSession, session_id)

    async def revoke_all_for_user(
        self,
        user_id: uuid.UUID,
        *,
        at: datetime,
        excluding: uuid.UUID | None = None,
    ) -> int:
        """Revoke every live session of one user; returns how many were revoked.

        The rows are loaded and mutated rather than updated in bulk. A single
        `UPDATE` would be fewer statements, but it also bypasses the identity
        map — the current request's own session row is usually already in it,
        and would go on reporting `revoked_at = None` for the rest of the
        transaction, which is precisely the value the next check reads. A member
        of staff has a handful of sessions, so the loop costs nothing and cannot
        disagree with itself.

        Atomicity does not depend on it being one statement: the caller's
        transaction commits all of these or none (`app.db.uow`).

        `excluding` exists for the password-change flow, which revokes
        everything *except* the session it has just issued.
        """
        statement = select(UserSession).where(
            UserSession.user_id == user_id, UserSession.revoked_at.is_(None)
        )
        if excluding is not None:
            statement = statement.where(UserSession.id != excluding)

        live = (await self._session.scalars(statement)).all()
        for user_session in live:
            user_session.revoked_at = at
        await self._session.flush()
        return len(live)

    async def revoke(self, user_session: UserSession, *, at: datetime) -> None:
        user_session.revoked_at = at
        await self._session.flush()

    async def touch(self, user_session: UserSession, *, at: datetime) -> None:
        """Record that the session was used, which is what defers the idle timeout."""
        user_session.last_seen_at = at
        await self._session.flush()
