"""One row per (user, authentication provider) — the seam Entra ID plugs into.

Release 1 creates `PASSWORD` identities holding an Argon2id hash. A federated
login later inserts a `MICROSOFT_ENTRA` row for the same user and changes
nothing about `users` (ADR-0006). Lockout counters live here rather than on the
user because they are a property of a credential, not of a person.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.enums import IdentityProvider
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

_PROVIDER_VALUES = ", ".join(f"'{provider.value}'" for provider in IdentityProvider)


class UserIdentity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user_identities"
    __table_args__ = (
        UniqueConstraint("provider", "provider_subject"),
        UniqueConstraint("user_id", "provider"),
        CheckConstraint(f"provider IN ({_PROVIDER_VALUES})", name="provider"),
        # A password identity without a hash would authenticate nobody and
        # would be indistinguishable from a federated one.
        CheckConstraint(
            "provider <> 'PASSWORD' OR secret_hash IS NOT NULL",
            name="password_requires_secret",
        ),
        CheckConstraint("failed_attempt_count >= 0", name="failed_attempt_count_non_negative"),
        Index(None, "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    #: The normalised email for `PASSWORD`; the IdP's stable object id later.
    provider_subject: Mapped[str] = mapped_column(String(320), nullable=False)
    #: Argon2id encoded hash. `NULL` for federated providers, which hold no secret.
    secret_hash: Mapped[str | None] = mapped_column(Text())
    secret_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_attempt_count: Mapped[int] = mapped_column(
        nullable=False, server_default=text("0"), default=0
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
