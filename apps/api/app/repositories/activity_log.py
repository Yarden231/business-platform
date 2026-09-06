"""Reads over `activity_log`.

Writes go through `app.audit.recorder` and nowhere else. This module reads, and
in Phase 2 it reads for exactly one reason: per-IP login throttling counts the
`USER_LOGIN_FAILED` rows of the trailing window.

Using the audit trail as the throttle's storage is a deliberate Release 1
choice. It needs no new table and no Redis, it is durable, and it works across
API instances — the three properties an in-process dictionary lacks
(docs/security.md §2). The action is passed in by the caller rather than named
here, because `app.repositories` sits below `app.audit` in the layering and may
not import the action catalogue.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_log import ActivityLog


class ActivityLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def count_by_action_and_ip(self, *, action: str, ip_address: str, since: datetime) -> int:
        """How many `action` rows this IP produced since `since`.

        Served by the `(action, occurred_at)` index; the IP is filtered from the
        rows that survive it, which at this scale is a handful.
        """
        return (
            await self._session.scalar(
                select(func.count(ActivityLog.id)).where(
                    ActivityLog.action == action,
                    ActivityLog.occurred_at >= since,
                    ActivityLog.ip_address == ip_address,
                )
            )
            or 0
        )
