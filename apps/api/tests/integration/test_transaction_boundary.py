"""The transaction boundary, proved rather than described.

The property the specification depends on is that a business change and the
audit row describing it cannot come apart: either both are committed or neither
is (ADR-0010). This is where that is demonstrated.

`_ProvisioningService` below exists only in this file. It is not a preview of
Phase 2's user management — it is the smallest possible thing shaped like a
service, so that the transaction helper is exercised through a real caller
rather than inline in a test body. Writing a fake `CaseService` to make the
point would be exactly the speculative structure this project avoids.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.actions import AuditAction, AuditEntityType
from app.audit.recorder import AuditRecorder
from app.db.uow import transaction
from app.domain.enums import UserRole
from app.models.activity_log import ActivityLog
from app.models.user import User


class _ProvisioningService:
    """Creates a user and records that it happened, in one transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._audit = AuditRecorder(session)

    async def create_user(self, *, email: str, full_name: str) -> User:
        async with transaction(self._session):
            user = User(email=email, full_name=full_name, role=UserRole.EMPLOYEE.value)
            self._session.add(user)
            await self._session.flush()
            await self._audit.record(
                action=AuditAction.USER_CREATED,
                entity_type=AuditEntityType.USER,
                entity_id=user.id,
                description=f"Staff account created for {email}.",
            )
            return user


async def count_rows(session: AsyncSession, model: type[User] | type[ActivityLog]) -> int:
    return await session.scalar(select(func.count()).select_from(model)) or 0


async def test_a_successful_use_case_commits_the_change_and_its_audit_row(
    db_session: AsyncSession,
) -> None:
    user = await _ProvisioningService(db_session).create_user(
        email="dana@example.com", full_name="Dana Cohen"
    )

    stored = await db_session.get(User, user.id)
    assert stored is not None

    audit_rows = (
        await db_session.scalars(select(ActivityLog).where(ActivityLog.entity_id == user.id))
    ).all()
    assert len(audit_rows) == 1
    assert audit_rows[0].action == AuditAction.USER_CREATED.value


async def test_a_failure_rolls_back_the_change_and_the_audit_row_together(
    db_session: AsyncSession,
) -> None:
    """The invariant: audit history cannot describe a change that did not happen."""
    await _ProvisioningService(db_session).create_user(
        email="dana@example.com", full_name="Dana Cohen"
    )
    users_before = await count_rows(db_session, User)
    events_before = await count_rows(db_session, ActivityLog)

    # The unique constraint on `users.email` refuses the second account, after
    # the service has already written its audit row.
    with pytest.raises(IntegrityError):
        await _ProvisioningService(db_session).create_user(
            email="dana@example.com", full_name="Dana Duplicate"
        )

    assert await count_rows(db_session, User) == users_before
    assert await count_rows(db_session, ActivityLog) == events_before


async def test_the_recorder_never_commits_on_its_own(db_session: AsyncSession) -> None:
    """A recorder used outside a transaction leaves nothing behind when it is rolled back."""
    await AuditRecorder(db_session).record(
        action=AuditAction.DOCUMENT_DOWNLOADED,
        entity_type=AuditEntityType.DOCUMENT_SUBMISSION,
        entity_id=uuid.uuid4(),
        description="A submission was downloaded.",
    )
    assert await count_rows(db_session, ActivityLog) == 1

    await db_session.rollback()

    assert await count_rows(db_session, ActivityLog) == 0


async def test_the_recorder_stamps_rows_with_the_current_request_id(
    db_session: AsyncSession,
) -> None:
    from app.core.request_context import reset_request_id, set_request_id

    set_request_id("11111111-2222-3333-4444-555555555555")
    try:
        entry = await AuditRecorder(db_session).record(
            action=AuditAction.USER_LOGGED_IN,
            entity_type=AuditEntityType.USER,
            description="A user signed in.",
        )
    finally:
        reset_request_id()

    assert entry.request_id == "11111111-2222-3333-4444-555555555555"
