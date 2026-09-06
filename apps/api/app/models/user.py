"""Internal staff accounts.

Clients and lawyers are not users in Release 1 — they are `people`, which
arrives in Phase 4. A user holds no credential: authentication material lives in
`user_identities` so that federating with Entra ID later is additive (ADR-0006).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.enums import UserRole
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

_ROLE_VALUES = ", ".join(f"'{role.value}'" for role in UserRole)


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        # `email` is the login identifier, so "same address, different
        # capitalisation" must not be able to become two accounts. The
        # application normalises; the database refuses anything else.
        CheckConstraint("email = lower(btrim(email)) AND email <> ''", name="email_normalized"),
        CheckConstraint("btrim(full_name) <> ''", name="full_name_not_blank"),
        CheckConstraint(f"role IN ({_ROLE_VALUES})", name="role"),
    )

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    #: Admin-provisioned accounts start with a one-time temporary password and
    #: cannot use any other endpoint until it is rotated (ADR-0026).
    must_change_password: Mapped[bool] = mapped_column(
        nullable=False, server_default=text("true"), default=True
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Set instead of deleting: audit rows must keep resolving to a real actor.
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: `NULL` only for the bootstrap admin, which by definition nobody created.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="RESTRICT")
    )
