"""Internal user administration (docs/api.md §5, docs/security.md §4).

Every method takes the acting `AuthenticatedActor` and re-checks the role gate
even though the router already applied one. That duplication is deliberate
defence in depth (docs/architecture.md §6): the service is also called by the
CLI, and a future scheduled job or second router must not be able to reach these
mutations by forgetting a dependency.

The temporary-password contract of ADR-0026 is enforced structurally rather than
by discipline: `create_user` and `reset_password` are the only functions that
ever see a temporary password, they hash it before it touches the database, and
they return it to their caller exactly once. No repository, model or schema in
this codebase has a field it could be stored in.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.actions import AuditAction, AuditEntityType
from app.audit.recorder import AuditRecorder
from app.auth.hashing import get_password_hasher
from app.auth.policies import ensure_role
from app.auth.sessions import SessionManager
from app.auth.tokens import generate_temporary_password
from app.core.errors import (
    ErrorDetail,
    LastAdminError,
    SelfDeactivationError,
    UserEmailConflictError,
    UserNotFoundError,
    ValidationFailedError,
)
from app.core.pagination import Page, PageRequest
from app.core.settings import Settings
from app.core.time import utc_now
from app.db.uow import transaction
from app.domain.actor import AuthenticatedActor
from app.domain.enums import IdentityProvider, UserRole
from app.models.user import User
from app.models.user_identity import UserIdentity
from app.repositories.sessions import SessionRepository
from app.repositories.user_identities import UserIdentityRepository
from app.repositories.users import UserRepository, normalize_email
from app.services.authentication import RequestOrigin


@dataclass(frozen=True, slots=True)
class UserView:
    """A staff account as an administrator sees it.

    What is *not* here is the point: no `secret_hash`, no identity row, no
    session, no `failed_attempt_count` and no `locked_until`. `is_active` is
    derived from `deactivated_at` so a client never has to reimplement the
    rule.
    """

    id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    must_change_password: bool
    is_active: bool
    deactivated_at: datetime | None
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class DirectoryEntry:
    """The three fields an assignee picker needs, and nothing else."""

    id: uuid.UUID
    full_name: str
    role: UserRole


@dataclass(frozen=True, slots=True)
class ProvisionedUser:
    """A newly created or reset account, with its one-time password.

    The password is in this object on its way into a single HTTP response and
    is never persisted in this form (ADR-0026).
    """

    user: UserView
    temporary_password: str


class UserService:
    """Everything under `/api/v1/users`."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._db = session
        self._settings = settings
        self._users = UserRepository(session)
        self._identities = UserIdentityRepository(session)
        self._audit = AuditRecorder(session)
        self._hasher = get_password_hasher(settings)
        self._sessions = SessionManager(
            sessions=SessionRepository(session),
            users=self._users,
            settings=settings,
        )

    # -- Reads -------------------------------------------------------------

    async def list_users(
        self,
        actor: AuthenticatedActor,
        *,
        page: PageRequest,
        query: str | None = None,
        role: UserRole | None = None,
        is_active: bool | None = None,
    ) -> Page[UserView]:
        ensure_role(actor, UserRole.ADMIN)
        users, total = await self._users.list_page(
            page, query=query, role=role, is_active=is_active
        )
        return Page(
            items=tuple(_view_of(user) for user in users),
            total=total,
            page=page.page,
            page_size=page.page_size,
        )

    async def get_user(self, actor: AuthenticatedActor, user_id: uuid.UUID) -> UserView:
        ensure_role(actor, UserRole.ADMIN)
        return _view_of(await self._require_user(user_id))

    async def list_directory(self, actor: AuthenticatedActor) -> tuple[DirectoryEntry, ...]:
        """Active staff, for assignee pickers and labels.

        Open to employees as well as admins: an employee has to be able to see
        who a case is assigned to (docs/security.md §4). It is *not* the people
        directory — no client, lawyer or other external party appears here,
        because they are not users in Release 1.
        """
        ensure_role(actor, UserRole.ADMIN, UserRole.EMPLOYEE)
        return tuple(
            DirectoryEntry(id=user.id, full_name=user.full_name, role=UserRole(user.role))
            for user in await self._users.list_directory()
        )

    # -- Mutations ---------------------------------------------------------

    async def create_user(
        self,
        actor: AuthenticatedActor,
        *,
        email: str,
        full_name: str,
        role: UserRole,
        origin: RequestOrigin,
    ) -> ProvisionedUser:
        """Provision a staff account with a one-time temporary password (ADR-0026).

        Admins may create admins: with no self-service reset, a firm with a
        single administrator has no way back from a lockout, and
        `docs/security.md` §2 names "keep more than one `ADMIN`" as the
        mitigation.
        """
        ensure_role(actor, UserRole.ADMIN)
        normalized = normalize_email(email)
        _ensure_present(full_name, field="full_name")

        if await self._users.exists_with_email(normalized):
            raise UserEmailConflictError

        temporary_password = generate_temporary_password()
        now = utc_now()
        user = User(
            email=normalized,
            full_name=full_name.strip(),
            role=role.value,
            must_change_password=True,
            created_by=actor.id,
        )
        identity = UserIdentity(
            user_id=user.id,
            provider=IdentityProvider.PASSWORD.value,
            provider_subject=normalized,
            secret_hash=self._hasher.hash_password(temporary_password),
            secret_updated_at=now,
        )

        try:
            async with transaction(self._db):
                self._users.add(user)
                self._identities.add(identity)
                await self._audit.record(
                    action=AuditAction.USER_CREATED,
                    entity_type=AuditEntityType.USER,
                    entity_id=user.id,
                    actor_user_id=actor.id,
                    description=f"Staff account created with role {role.value}.",
                    metadata={
                        "role": role.value,
                        "provider": IdentityProvider.PASSWORD.value,
                        "must_change_password": True,
                    },
                    ip_address=origin.ip_address,
                )
        except IntegrityError as exc:
            # The check above is a courtesy; this is the guarantee. Two
            # concurrent creations for one address both pass the read and one
            # loses at `UNIQUE (users.email)`.
            raise UserEmailConflictError from exc

        return ProvisionedUser(
            user=await self._view_after_commit(user),
            temporary_password=temporary_password,
        )

    async def update_user(
        self,
        actor: AuthenticatedActor,
        user_id: uuid.UUID,
        *,
        full_name: str | None = None,
        role: UserRole | None = None,
        deactivated: bool | None = None,
        origin: RequestOrigin,
    ) -> UserView:
        """Apply an explicit allowlist of changes: name, role, activation state.

        Deactivation is not a delete — it sets `deactivated_at`, keeps the row
        so audit history still resolves to a real actor, and revokes every live
        session of the target in the same transaction.
        """
        ensure_role(actor, UserRole.ADMIN)
        user = await self._require_user(user_id)

        if deactivated is True and user.id == actor.id:
            raise SelfDeactivationError
        if await self._would_remove_last_admin(user, role=role, deactivated=deactivated):
            raise LastAdminError

        changes: dict[str, Any] = {}
        if full_name is not None:
            _ensure_present(full_name, field="full_name")
            stripped = full_name.strip()
            if stripped != user.full_name:
                changes["full_name"] = {"before": user.full_name, "after": stripped}
                user.full_name = stripped
        if role is not None and role.value != user.role:
            changes["role"] = {"before": user.role, "after": role.value}
            user.role = role.value

        activation: AuditAction | None = None
        if deactivated is True and user.deactivated_at is None:
            activation = AuditAction.USER_DEACTIVATED
        elif deactivated is False and user.deactivated_at is not None:
            activation = AuditAction.USER_ACTIVATED

        if not changes and activation is None:
            return _view_of(user)

        async with transaction(self._db):
            revoked = 0
            if activation is AuditAction.USER_DEACTIVATED:
                user.deactivated_at = utc_now()
                revoked = await self._sessions.revoke_all_for_user(user.id)
            elif activation is AuditAction.USER_ACTIVATED:
                # Reactivation restores the account, not its old sessions: those
                # were revoked when it was disabled and stay that way.
                user.deactivated_at = None

            if changes:
                await self._audit.record(
                    action=AuditAction.USER_UPDATED,
                    entity_type=AuditEntityType.USER,
                    entity_id=user.id,
                    actor_user_id=actor.id,
                    description="Staff account updated.",
                    changes=changes,
                    ip_address=origin.ip_address,
                )
            if activation is not None:
                await self._audit.record(
                    action=activation,
                    entity_type=AuditEntityType.USER,
                    entity_id=user.id,
                    actor_user_id=actor.id,
                    description=(
                        "Staff account deactivated."
                        if activation is AuditAction.USER_DEACTIVATED
                        else "Staff account reactivated."
                    ),
                    metadata={"revoked_session_count": revoked},
                    ip_address=origin.ip_address,
                )
        return await self._view_after_commit(user)

    async def reset_password(
        self,
        actor: AuthenticatedActor,
        user_id: uuid.UUID,
        *,
        origin: RequestOrigin,
    ) -> ProvisionedUser:
        """Issue a new temporary password for somebody else (ADR-0026).

        This is the whole account-recovery story in Release 1: there is no
        email service, so an admin does this and reads the password out of
        band. It clears any lockout, because "locked out" is the main reason it
        is called, and revokes every session of the target so a stolen one
        cannot survive the reset.
        """
        ensure_role(actor, UserRole.ADMIN)
        user = await self._require_user(user_id)
        identity = await self._identities.get_for_user(
            user_id=user.id, provider=IdentityProvider.PASSWORD
        )
        if identity is None:  # pragma: no cover - every Release 1 account has one
            raise UserNotFoundError

        temporary_password = generate_temporary_password()

        async with transaction(self._db):
            now = utc_now()
            identity.secret_hash = self._hasher.hash_password(temporary_password)
            identity.secret_updated_at = now
            identity.failed_attempt_count = 0
            identity.locked_until = None
            user.must_change_password = True

            revoked = await self._sessions.revoke_all_for_user(user.id)
            await self._audit.record(
                action=AuditAction.USER_PASSWORD_RESET,
                entity_type=AuditEntityType.USER,
                entity_id=user.id,
                actor_user_id=actor.id,
                description="Administrator issued a new temporary password.",
                metadata={"revoked_session_count": revoked, "must_change_password": True},
                ip_address=origin.ip_address,
            )

        return ProvisionedUser(
            user=await self._view_after_commit(user),
            temporary_password=temporary_password,
        )

    # -- Internals ---------------------------------------------------------

    async def _view_after_commit(self, user: User) -> UserView:
        """Re-read the row so the timestamps in the response are PostgreSQL's own.

        `created_at` and `updated_at` are server defaults, and `updated_at` is
        rewritten by the column's `onupdate`, so the in-memory object is either
        unloaded or stale by the time a mutation has committed. One primary-key
        read is cheaper than a response that is approximately right.
        """
        await self._db.refresh(user)
        return _view_of(user)

    async def _require_user(self, user_id: uuid.UUID) -> User:
        user = await self._users.get(user_id)
        if user is None:
            raise UserNotFoundError
        return user

    async def _would_remove_last_admin(
        self, user: User, *, role: UserRole | None, deactivated: bool | None
    ) -> bool:
        """Whether this change would leave the firm with no active administrator."""
        if user.role != UserRole.ADMIN.value or user.deactivated_at is not None:
            return False
        losing_role = role is not None and role is not UserRole.ADMIN
        losing_account = deactivated is True
        if not (losing_role or losing_account):
            return False
        return await self._users.count_active_admins(excluding=user.id) == 0


def _view_of(user: User) -> UserView:
    """The one mapping from the ORM row to what leaves the service layer."""
    return UserView(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=UserRole(user.role),
        must_change_password=user.must_change_password,
        is_active=user.deactivated_at is None,
        deactivated_at=user.deactivated_at,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


def _ensure_present(value: str, *, field: str) -> None:
    """Reject a blank display name before PostgreSQL's `CHECK` does.

    The constraint is the guarantee; this is what turns it into a `422` naming
    the field instead of a `500` from a driver error.
    """
    if not value.strip():
        raise ValidationFailedError(details=[ErrorDetail(field=field, issue="blank")])
