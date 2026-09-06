"""Writing audit rows.

The recorder is bound to the caller's `AsyncSession` and **never commits**. It
adds a row and flushes it, so a constraint violation surfaces where it happened
rather than at the end of the request, and the row lands or is discarded with
the change it describes:

    async with transaction(session):
        case.status = to_status
        await recorder.record(
            action=AuditAction.CASE_STATUS_CHANGED,
            entity_type=AuditEntityType.CASE,
            entity_id=case.id,
            case_id=case.id,
            description="Case status changed to DOCUMENTS_REVIEW.",
        )

There is no `update` and no `delete`: the table rejects both at the database
level, and the application does not pretend otherwise.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.actions import AuditAction, AuditEntityType
from app.core.request_context import get_request_id
from app.core.time import utc_now
from app.models.activity_log import ActivityLog


class AuditRecorder:
    """Appends business events to `activity_log` inside the caller's transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        *,
        action: AuditAction,
        entity_type: AuditEntityType,
        description: str,
        actor_user_id: uuid.UUID | None = None,
        entity_id: uuid.UUID | None = None,
        case_id: uuid.UUID | None = None,
        metadata: dict[str, Any] | None = None,
        changes: dict[str, Any] | None = None,
        request_id: str | None = None,
        ip_address: str | None = None,
        occurred_at: datetime | None = None,
    ) -> ActivityLog:
        """Append one event and return the row, without committing.

        `request_id` defaults to the current request's id, so a caller inside a
        request never has to thread it through; a background job or a script
        simply records `None`.
        """
        entry = ActivityLog(
            occurred_at=occurred_at or utc_now(),
            actor_user_id=actor_user_id,
            action=action.value,
            entity_type=entity_type.value,
            entity_id=entity_id,
            case_id=case_id,
            description=description,
            event_metadata=metadata if metadata is not None else {},
            changes=changes,
            request_id=request_id if request_id is not None else get_request_id(),
            ip_address=ip_address,
        )
        self._session.add(entry)
        await self._session.flush()
        return entry
