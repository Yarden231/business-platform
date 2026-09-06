"""Bootstrapping the first administrator (docs/security.md §9).

The properties worth testing here are the refusals. A bootstrap command that
seeds a default account, that quietly resets an existing admin's password on a
second run, or that accepts a weaker password than the API would, is a back
door — and all three are the kind of thing that gets added later "for
convenience" unless a test says otherwise.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.actions import AuditAction
from app.auth.hashing import get_password_hasher
from app.core.errors import PasswordInvalidError
from app.core.settings import get_settings
from app.domain.enums import UserRole
from app.models.activity_log import ActivityLog
from app.models.user import User
from app.repositories.users import UserRepository
from app.services.admin_bootstrap import (
    AdminAlreadyExistsError,
    AdminBootstrapService,
    BootstrapOutcome,
)
from tests.support.accounts import create_admin, create_employee, password_identity

EMAIL = "founder@example.com"
PASSWORD = "bootstrap development passphrase"


@pytest.fixture
def bootstrap(db_session: AsyncSession) -> AdminBootstrapService:
    return AdminBootstrapService(db_session, get_settings())


class TestCreation:
    async def test_it_creates_an_admin(
        self, bootstrap: AdminBootstrapService, db_session: AsyncSession
    ) -> None:
        result = await bootstrap.create_initial_admin(
            email=EMAIL, full_name="Founding Admin", password=PASSWORD
        )

        assert result.outcome is BootstrapOutcome.CREATED
        user = await UserRepository(db_session).get_by_email(EMAIL)
        assert user is not None
        assert user.role == UserRole.ADMIN.value
        assert user.deactivated_at is None

    async def test_it_creates_a_password_identity(
        self, bootstrap: AdminBootstrapService, db_session: AsyncSession
    ) -> None:
        await bootstrap.create_initial_admin(
            email=EMAIL, full_name="Founding Admin", password=PASSWORD
        )

        user = await UserRepository(db_session).get_by_email(EMAIL)
        assert user is not None
        identity = await password_identity(db_session, user.id)
        assert identity.provider_subject == EMAIL

    async def test_the_password_goes_through_the_ordinary_hasher(
        self, bootstrap: AdminBootstrapService, db_session: AsyncSession
    ) -> None:
        """No weaker rules and no different algorithm for the bootstrap account."""
        await bootstrap.create_initial_admin(
            email=EMAIL, full_name="Founding Admin", password=PASSWORD
        )

        user = await UserRepository(db_session).get_by_email(EMAIL)
        assert user is not None
        identity = await password_identity(db_session, user.id)
        assert identity.secret_hash is not None
        assert identity.secret_hash.startswith("$argon2id$")
        assert PASSWORD not in identity.secret_hash
        assert get_password_hasher(get_settings()).verify_password(
            password=PASSWORD, secret_hash=identity.secret_hash
        )

    async def test_the_email_is_normalised(
        self, bootstrap: AdminBootstrapService, db_session: AsyncSession
    ) -> None:
        result = await bootstrap.create_initial_admin(
            email="  Founder@Example.COM  ", full_name="Founding Admin", password=PASSWORD
        )

        assert result.email == EMAIL
        assert await UserRepository(db_session).get_by_email(EMAIL) is not None

    async def test_the_name_is_trimmed(
        self, bootstrap: AdminBootstrapService, db_session: AsyncSession
    ) -> None:
        await bootstrap.create_initial_admin(
            email=EMAIL, full_name="  Founding Admin  ", password=PASSWORD
        )

        user = await UserRepository(db_session).get_by_email(EMAIL)
        assert user is not None
        assert user.full_name == "Founding Admin"

    async def test_no_rotation_is_forced(
        self, bootstrap: AdminBootstrapService, db_session: AsyncSession
    ) -> None:
        """The operator chose this password at a terminal; nothing travelled out of band."""
        await bootstrap.create_initial_admin(
            email=EMAIL, full_name="Founding Admin", password=PASSWORD
        )

        user = await UserRepository(db_session).get_by_email(EMAIL)
        assert user is not None
        assert user.must_change_password is False

    async def test_it_is_audited_as_a_system_action(
        self, bootstrap: AdminBootstrapService, db_session: AsyncSession
    ) -> None:
        """A null actor means the system acted; blaming the new admin would be a lie."""
        await bootstrap.create_initial_admin(
            email=EMAIL, full_name="Founding Admin", password=PASSWORD
        )

        entry = await db_session.scalar(
            select(ActivityLog).where(ActivityLog.action == AuditAction.USER_CREATED.value)
        )
        assert entry is not None
        assert entry.actor_user_id is None
        assert entry.event_metadata["bootstrap"] is True
        assert PASSWORD not in f"{entry.description} {entry.event_metadata}"


class TestRefusals:
    async def test_a_second_admin_is_refused(
        self, bootstrap: AdminBootstrapService, db_session: AsyncSession
    ) -> None:
        """Further admins go through the authenticated, audited API."""
        await create_admin(db_session, email="existing@example.com")

        with pytest.raises(AdminAlreadyExistsError):
            await bootstrap.create_initial_admin(
                email=EMAIL, full_name="Founding Admin", password=PASSWORD
            )

    async def test_re_running_it_for_the_same_admin_changes_nothing(
        self, bootstrap: AdminBootstrapService, db_session: AsyncSession
    ) -> None:
        """Safe in a provisioning script that runs twice — and not a silent reset."""
        await bootstrap.create_initial_admin(
            email=EMAIL, full_name="Founding Admin", password=PASSWORD
        )
        user = await UserRepository(db_session).get_by_email(EMAIL)
        assert user is not None
        before = (await password_identity(db_session, user.id)).secret_hash

        result = await bootstrap.create_initial_admin(
            email=EMAIL, full_name="Someone Else", password="a completely different one"
        )

        assert result.outcome is BootstrapOutcome.ALREADY_EXISTS
        identity = await password_identity(db_session, user.id)
        await db_session.refresh(identity)
        assert identity.secret_hash == before
        await db_session.refresh(user)
        assert user.full_name == "Founding Admin"

    async def test_it_creates_no_duplicate_account(
        self, bootstrap: AdminBootstrapService, db_session: AsyncSession
    ) -> None:
        for _ in range(3):
            await bootstrap.create_initial_admin(
                email=EMAIL, full_name="Founding Admin", password=PASSWORD
            )

        count = await db_session.scalar(select(func.count()).select_from(User))
        assert count == 1

    async def test_an_address_belonging_to_an_employee_is_refused(
        self, bootstrap: AdminBootstrapService, db_session: AsyncSession
    ) -> None:
        """Promoting an existing account by re-running a bootstrap script is not a thing."""
        await create_employee(db_session, email=EMAIL)

        with pytest.raises(AdminAlreadyExistsError):
            await bootstrap.create_initial_admin(
                email=EMAIL, full_name="Founding Admin", password=PASSWORD
            )

    async def test_a_weak_password_is_refused(self, bootstrap: AdminBootstrapService) -> None:
        with pytest.raises(PasswordInvalidError):
            await bootstrap.create_initial_admin(
                email=EMAIL, full_name="Founding Admin", password="short"
            )

    async def test_a_trivial_password_is_refused(self, bootstrap: AdminBootstrapService) -> None:
        with pytest.raises(PasswordInvalidError):
            await bootstrap.create_initial_admin(
                email=EMAIL, full_name="Founding Admin", password="passwordpassword"
            )

    @pytest.mark.parametrize("email", ["", "   "])
    async def test_a_missing_email_is_refused(
        self, bootstrap: AdminBootstrapService, email: str
    ) -> None:
        """No email, no account. There is deliberately no default."""
        with pytest.raises(ValueError, match="email"):
            await bootstrap.create_initial_admin(
                email=email, full_name="Founding Admin", password=PASSWORD
            )

    @pytest.mark.parametrize("full_name", ["", "   "])
    async def test_a_missing_name_is_refused(
        self, bootstrap: AdminBootstrapService, full_name: str
    ) -> None:
        with pytest.raises(ValueError, match="name"):
            await bootstrap.create_initial_admin(
                email=EMAIL, full_name=full_name, password=PASSWORD
            )

    async def test_a_refused_bootstrap_writes_nothing(
        self, bootstrap: AdminBootstrapService, db_session: AsyncSession
    ) -> None:
        with pytest.raises(PasswordInvalidError):
            await bootstrap.create_initial_admin(
                email=EMAIL, full_name="Founding Admin", password="short"
            )

        assert await db_session.scalar(select(func.count()).select_from(User)) == 0

    async def test_a_deactivated_admin_does_not_count_as_administrable(
        self, bootstrap: AdminBootstrapService, db_session: AsyncSession
    ) -> None:
        """An instance whose only admin is disabled has to be recoverable."""
        await create_admin(db_session, email="disabled@example.com", deactivated=True)

        result = await bootstrap.create_initial_admin(
            email=EMAIL, full_name="Founding Admin", password=PASSWORD
        )

        assert result.outcome is BootstrapOutcome.CREATED
