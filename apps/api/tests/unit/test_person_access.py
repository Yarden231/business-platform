"""The person-access predicate, unit-tested without a database (ADR-0027)."""

from __future__ import annotations

import uuid

import pytest

from app.auth.policies import ensure_can_archive_person, ensure_can_edit_person
from app.core.errors import ErrorCode, ForbiddenError, PersonAccessDeniedError
from app.domain.actor import AuthenticatedActor
from app.domain.enums import UserRole
from app.services.person_access import PersonAccessService


def _actor(*, role: UserRole) -> AuthenticatedActor:
    return AuthenticatedActor(
        id=uuid.uuid4(),
        email="staff@example.com",
        full_name="Staff Member",
        role=role,
        must_change_password=False,
    )


class TestHasFullAccessPhase4:
    """Until cases exist, only an admin can honestly hold full access."""

    async def test_an_admin_has_full_access(self) -> None:
        service = PersonAccessService(session=None)  # type: ignore[arg-type]
        assert await service.has_full_access(_actor(role=UserRole.ADMIN), uuid.uuid4()) is True

    async def test_an_employee_does_not(self) -> None:
        service = PersonAccessService(session=None)  # type: ignore[arg-type]
        assert await service.has_full_access(_actor(role=UserRole.EMPLOYEE), uuid.uuid4()) is False


class TestEditPolicy:
    def test_full_access_is_required(self) -> None:
        ensure_can_edit_person(has_full_access=True)

    def test_summary_only_access_is_refused(self) -> None:
        with pytest.raises(PersonAccessDeniedError) as raised:
            ensure_can_edit_person(has_full_access=False)
        assert raised.value.code is ErrorCode.PERSON_ACCESS_DENIED
        assert raised.value.status_code == 403


class TestArchivePolicy:
    def test_an_admin_may_archive(self) -> None:
        ensure_can_archive_person(_actor(role=UserRole.ADMIN))

    def test_an_employee_may_not(self) -> None:
        with pytest.raises(ForbiddenError) as raised:
            ensure_can_archive_person(_actor(role=UserRole.EMPLOYEE))
        assert raised.value.code is ErrorCode.FORBIDDEN
