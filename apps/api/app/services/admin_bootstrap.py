"""Creating the first administrator.

Every other account in the system is created by an admin. This is the one that
cannot be, so it is created out of band by somebody with database access, and it
is the only account whose `created_by` is `NULL` — by definition nobody created
it (docs/domain-model.md §3).

The safety properties are the reason this is a service rather than a script with
SQL in it:

* **No default account, ever.** There is no seeded email, no seeded password and
  no fallback. If the operator supplies nothing, nothing is created. A default
  administrator is the single worst thing this codebase could ship
  (docs/security.md §9).
* **It will not create a second one.** An existing active admin means the system
  is already administrable, and further admins are created through
  `POST /api/v1/users` where the action is authenticated and audited. Re-running
  it for an account that already exists reports that and changes nothing, so it
  is safe in a provisioning script that may run twice.
* **The password goes through the same policy and the same hasher** as every
  other password. The bootstrap is not a back door with weaker rules.

`must_change_password` is `False` here, unlike an admin-provisioned account: the
operator chose this password themselves at a terminal, so there is no temporary
credential that travelled out of band and needs rotating (ADR-0026).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.actions import AuditAction, AuditEntityType
from app.audit.recorder import AuditRecorder
from app.auth.hashing import get_password_hasher
from app.auth.password_policy import ensure_password_meets_policy
from app.core.errors import ConflictError
from app.core.settings import Settings
from app.core.time import utc_now
from app.db.uow import transaction
from app.domain.enums import IdentityProvider, UserRole
from app.models.user import User
from app.models.user_identity import UserIdentity
from app.repositories.user_identities import UserIdentityRepository
from app.repositories.users import UserRepository, normalize_email


class BootstrapOutcome(StrEnum):
    CREATED = "CREATED"
    #: The requested address is already an active admin. Nothing was changed —
    #: in particular, the password was **not** reset, because that would make a
    #: re-run of a provisioning script a silent credential rotation.
    ALREADY_EXISTS = "ALREADY_EXISTS"


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    outcome: BootstrapOutcome
    email: str


class AdminAlreadyExistsError(ConflictError):
    """A different administrator already exists, so bootstrapping is not needed."""

    message = (
        "An active administrator already exists. Create further accounts through "
        "POST /api/v1/users so the action is authenticated and audited."
    )


class AdminBootstrapService:
    """Creates the initial `ADMIN` account and its `PASSWORD` identity."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._db = session
        self._settings = settings
        self._users = UserRepository(session)
        self._identities = UserIdentityRepository(session)
        self._audit = AuditRecorder(session)
        self._hasher = get_password_hasher(settings)

    async def create_initial_admin(
        self, *, email: str, full_name: str, password: str
    ) -> BootstrapResult:
        """Create the first administrator, or report that one already exists."""
        normalized = normalize_email(email)
        if not normalized:
            raise ValueError("An email address is required")
        if not full_name.strip():
            raise ValueError("A full name is required")
        ensure_password_meets_policy(password)

        existing = await self._users.get_by_email(normalized)
        if existing is not None:
            if existing.role == UserRole.ADMIN.value and existing.deactivated_at is None:
                return BootstrapResult(outcome=BootstrapOutcome.ALREADY_EXISTS, email=normalized)
            raise AdminAlreadyExistsError(
                "That address already belongs to an account. Bootstrapping will not "
                "modify an existing user."
            )

        if await self._users.count_active_admins() > 0:
            raise AdminAlreadyExistsError

        user = User(
            email=normalized,
            full_name=full_name.strip(),
            role=UserRole.ADMIN.value,
            # The operator typed this password; there is nothing to rotate.
            must_change_password=False,
            created_by=None,
        )
        identity = UserIdentity(
            user_id=user.id,
            provider=IdentityProvider.PASSWORD.value,
            provider_subject=normalized,
            secret_hash=self._hasher.hash_password(password),
            secret_updated_at=utc_now(),
        )

        async with transaction(self._db):
            self._users.add(user)
            self._identities.add(identity)
            await self._audit.record(
                action=AuditAction.USER_CREATED,
                entity_type=AuditEntityType.USER,
                entity_id=user.id,
                # `NULL` means the system acted rather than a person
                # (docs/domain-model.md §7). Attributing it to the new admin
                # would claim they created themselves.
                actor_user_id=None,
                description="Bootstrap ADMIN account created outside the API.",
                metadata={
                    "role": UserRole.ADMIN.value,
                    "provider": IdentityProvider.PASSWORD.value,
                    "bootstrap": True,
                },
            )

        return BootstrapResult(outcome=BootstrapOutcome.CREATED, email=normalized)
