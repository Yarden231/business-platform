"""Request and response models for `/api/v1/users` (docs/api.md §5)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.domain.enums import UserRole
from app.schemas.base import RequestModel
from app.services.users import DirectoryEntry, UserView

_FULL_NAME_MAX_LENGTH = 200


class UserResponse(BaseModel):
    """A staff account as an administrator sees it.

    Built field by field from a `UserView`, never from the ORM row, so adding a
    column to `users` cannot publish it here (docs/api.md §1). Absent on
    purpose: the identity row and its `secret_hash`, every session, and the
    `failed_attempt_count`/`locked_until` lockout counters (docs/security.md §5).
    """

    id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    must_change_password: bool
    is_active: bool = Field(description="False once the account has been deactivated.")
    deactivated_at: datetime | None
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, view: UserView) -> UserResponse:
        return cls(
            id=view.id,
            email=view.email,
            full_name=view.full_name,
            role=view.role,
            must_change_password=view.must_change_password,
            is_active=view.is_active,
            deactivated_at=view.deactivated_at,
            last_login_at=view.last_login_at,
            created_at=view.created_at,
            updated_at=view.updated_at,
        )


class UserCreateRequest(RequestModel):
    """Body for `POST /api/v1/users`.

    `role` accepts `ADMIN` as well as `EMPLOYEE`: with no self-service password
    reset, a firm with one administrator has no way back from a lockout, and
    keeping a second `ADMIN` is the documented mitigation (docs/security.md §2).
    """

    email: EmailStr = Field(
        description="Login identifier. Normalised to lower case and cannot be changed later."
    )
    full_name: str = Field(min_length=1, max_length=_FULL_NAME_MAX_LENGTH)
    role: UserRole


class UserUpdateRequest(RequestModel):
    """Body for `PATCH /api/v1/users/{user_id}`.

    An explicit allowlist, not a partial model of the row: `email`,
    `must_change_password`, `created_by` and every timestamp are absent because
    no administrator may set them directly. Omitted fields are left alone.
    """

    full_name: str | None = Field(default=None, min_length=1, max_length=_FULL_NAME_MAX_LENGTH)
    role: UserRole | None = None
    deactivated: bool | None = Field(
        default=None,
        description=(
            "True deactivates the account and revokes all of its sessions immediately; "
            "false reactivates it without restoring the old sessions."
        ),
    )


class ProvisionedUserResponse(BaseModel):
    """The response to account creation and to an admin password reset (ADR-0026).

    `temporary_password` appears in this one response and is never retrievable
    again: only its Argon2id hash is stored. The admin passes it to the user out
    of band, and the user must change it before any other endpoint will work.
    """

    user: UserResponse
    temporary_password: str = Field(
        description="Shown exactly once. Not stored in plaintext and not recoverable."
    )


class DirectoryEntryResponse(BaseModel):
    """`GET /api/v1/users/directory` — the three fields an assignee picker needs.

    Internal staff only. This is not the people directory: clients, lawyers and
    other external parties are `people`, not users.
    """

    id: uuid.UUID
    full_name: str
    role: UserRole

    @classmethod
    def of(cls, entry: DirectoryEntry) -> DirectoryEntryResponse:
        return cls(id=entry.id, full_name=entry.full_name, role=entry.role)
