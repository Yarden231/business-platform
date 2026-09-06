"""Role gates and the temporary-password gate (docs/security.md §4).

Pure functions over an actor, so authorization is provable without a request.
The endpoint-level consequences are proved separately, over HTTP, in
`tests/integration/test_authorization.py`.
"""

from __future__ import annotations

import uuid

import pytest

from app.auth.policies import ensure_password_rotated, ensure_role, has_role
from app.core.errors import ErrorCode, ForbiddenError, PasswordChangeRequiredError
from app.domain.actor import AuthenticatedActor
from app.domain.enums import UserRole


def actor(
    *, role: UserRole = UserRole.EMPLOYEE, must_change_password: bool = False
) -> AuthenticatedActor:
    return AuthenticatedActor(
        id=uuid.uuid4(),
        email="staff@example.com",
        full_name="Staff Member",
        role=role,
        must_change_password=must_change_password,
    )


class TestRoleChecks:
    def test_a_matching_role_passes(self) -> None:
        assert has_role(actor(role=UserRole.ADMIN), UserRole.ADMIN) is True

    def test_a_non_matching_role_fails(self) -> None:
        assert has_role(actor(role=UserRole.EMPLOYEE), UserRole.ADMIN) is False

    def test_any_of_several_allowed_roles_passes(self) -> None:
        assert has_role(actor(role=UserRole.EMPLOYEE), UserRole.ADMIN, UserRole.EMPLOYEE) is True

    def test_no_allowed_role_means_nobody(self) -> None:
        """Deny by default: an empty allow-list is not an open door."""
        assert has_role(actor(role=UserRole.ADMIN)) is False


class TestRoleEnforcement:
    def test_an_admin_passes_an_admin_gate(self) -> None:
        ensure_role(actor(role=UserRole.ADMIN), UserRole.ADMIN)

    def test_an_employee_is_refused_by_an_admin_gate(self) -> None:
        with pytest.raises(ForbiddenError) as raised:
            ensure_role(actor(role=UserRole.EMPLOYEE), UserRole.ADMIN)

        assert raised.value.code is ErrorCode.FORBIDDEN
        assert raised.value.status_code == 403

    def test_the_refusal_does_not_name_the_required_role(self) -> None:
        """The message is for a person, not a map of the permission model."""
        with pytest.raises(ForbiddenError) as raised:
            ensure_role(actor(role=UserRole.EMPLOYEE), UserRole.ADMIN)

        assert "ADMIN" not in raised.value.message


class TestTemporaryPasswordGate:
    def test_a_rotated_account_passes(self) -> None:
        ensure_password_rotated(actor(must_change_password=False))

    def test_an_account_holding_a_temporary_password_is_refused(self) -> None:
        with pytest.raises(PasswordChangeRequiredError) as raised:
            ensure_password_rotated(actor(must_change_password=True))

        assert raised.value.code is ErrorCode.PASSWORD_CHANGE_REQUIRED
        assert raised.value.status_code == 403

    def test_the_gate_applies_to_an_admin_too(self) -> None:
        """A bootstrapped admin rotates its own temporary password like anyone else."""
        with pytest.raises(PasswordChangeRequiredError):
            ensure_password_rotated(actor(role=UserRole.ADMIN, must_change_password=True))


class TestActorSafety:
    def test_the_actor_carries_no_secret_material(self) -> None:
        """It is what every authenticated endpoint receives, so its shape is the blast radius."""
        assert set(AuthenticatedActor.__dataclass_fields__) == {
            "id",
            "email",
            "full_name",
            "role",
            "must_change_password",
        }

    def test_the_actor_cannot_be_mutated_mid_request(self) -> None:
        with pytest.raises(AttributeError):
            actor().role = UserRole.ADMIN  # type: ignore[misc]
