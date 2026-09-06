"""`activity_log` is append-only, and PostgreSQL is what enforces it.

The audit trail is evidence about a firm's professional work. "The application
has no update endpoint" is a promise about today's code; a trigger is a property
of the data (ADR-0010). These tests go around the ORM entirely and issue raw
SQL, because that is exactly the access path a convention would not stop.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.actions import AuditAction, AuditEntityType
from app.audit.recorder import AuditRecorder
from app.models.activity_log import ActivityLog


@pytest.fixture
async def recorded_event(db_session: AsyncSession) -> ActivityLog:
    return await AuditRecorder(db_session).record(
        action=AuditAction.USER_CREATED,
        entity_type=AuditEntityType.USER,
        entity_id=uuid.uuid4(),
        description="An employee account was created.",
        metadata={"role": "EMPLOYEE"},
    )


class TestAppending:
    async def test_an_event_can_be_recorded(self, recorded_event: ActivityLog) -> None:
        assert recorded_event.id is not None
        assert recorded_event.occurred_at.tzinfo is not None
        assert recorded_event.event_metadata == {"role": "EMPLOYEE"}

    async def test_the_row_is_readable_back(
        self, db_session: AsyncSession, recorded_event: ActivityLog
    ) -> None:
        stored = await db_session.get(ActivityLog, recorded_event.id)

        assert stored is not None
        assert stored.action == "USER_CREATED"
        assert stored.description == "An employee account was created."

    async def test_the_json_column_is_named_metadata_in_the_database(
        self, db_session: AsyncSession, recorded_event: ActivityLog
    ) -> None:
        """The Python attribute is `event_metadata`; the contract is the column name."""
        value = await db_session.scalar(
            text("SELECT metadata->>'role' FROM activity_log WHERE id = :id"),
            {"id": recorded_event.id},
        )

        assert value == "EMPLOYEE"

    async def test_a_blank_action_is_refused(self, db_session: AsyncSession) -> None:
        with pytest.raises(DBAPIError):
            await db_session.execute(
                text(
                    """
                    INSERT INTO activity_log (id, action, entity_type, description)
                    VALUES (gen_random_uuid(), '   ', 'USER', 'nothing')
                    """
                )
            )


class TestImmutability:
    async def test_update_is_rejected(
        self, db_session: AsyncSession, recorded_event: ActivityLog
    ) -> None:
        with pytest.raises(DBAPIError, match="append-only"):
            await db_session.execute(
                text("UPDATE activity_log SET description = 'rewritten' WHERE id = :id"),
                {"id": recorded_event.id},
            )

    async def test_delete_is_rejected(
        self, db_session: AsyncSession, recorded_event: ActivityLog
    ) -> None:
        with pytest.raises(DBAPIError, match="append-only"):
            await db_session.execute(
                text("DELETE FROM activity_log WHERE id = :id"), {"id": recorded_event.id}
            )

    async def test_a_blanket_delete_is_rejected_too(
        self, db_session: AsyncSession, recorded_event: ActivityLog
    ) -> None:
        assert recorded_event.id is not None

        with pytest.raises(DBAPIError, match="append-only"):
            await db_session.execute(text("DELETE FROM activity_log"))

    async def test_truncate_is_rejected(self, db_session: AsyncSession) -> None:
        """Row triggers do not fire for TRUNCATE; without a statement trigger this works."""
        with pytest.raises(DBAPIError, match="append-only"):
            await db_session.execute(text("TRUNCATE activity_log"))

    async def test_the_original_row_is_untouched_after_a_rejected_update(
        self, db_session: AsyncSession
    ) -> None:
        entry = await AuditRecorder(db_session).record(
            action=AuditAction.USER_DEACTIVATED,
            entity_type=AuditEntityType.USER,
            entity_id=uuid.uuid4(),
            description="An employee account was deactivated.",
        )
        entry_id = entry.id
        await db_session.commit()

        with pytest.raises(DBAPIError, match="append-only"):
            await db_session.execute(
                text("UPDATE activity_log SET description = 'rewritten' WHERE id = :id"),
                {"id": entry_id},
            )
        await db_session.rollback()

        surviving = await db_session.scalar(
            text("SELECT description FROM activity_log WHERE id = :id"), {"id": entry_id}
        )
        assert surviving == "An employee account was deactivated."
