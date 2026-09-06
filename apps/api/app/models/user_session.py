"""Server-side sessions.

The cookie carries an opaque 256-bit random token; this table stores only its
SHA-256 hash, so a database read cannot impersonate anybody (ADR-0004). The
class is `UserSession` rather than `Session` purely so it cannot be confused
with SQLAlchemy's `Session` at an import site; the table is `sessions`.

Phase 1 creates the persistence only. Issuing, validating, refreshing and
revoking sessions is Phase 2.
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
    func,
)
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import UUIDPrimaryKeyMixin


class UserSession(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "sessions"
    __table_args__ = (
        UniqueConstraint("token_hash"),
        CheckConstraint("expires_at > issued_at", name="expires_after_issued"),
        # "Revoke every session of this user" — password change, deactivation,
        # incident response — is the query that has to stay cheap.
        Index(None, "user_id", "revoked_at"),
        # Pruning expired rows, the only routinely deletable data in the schema.
        Index(None, "expires_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    #: SHA-256 of the cookie token, hex-encoded. Never the token itself.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Binds the double-submit CSRF token to this session (docs/security.md §3).
    csrf_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Also the row's creation instant; a separate `created_at` would always
    #: hold the same value.
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    #: Drives the idle timeout; refreshed at most once per minute from Phase 2.
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    #: Truncated by the application before storage.
    user_agent: Mapped[str | None] = mapped_column(Text())
    ip_address: Mapped[str | None] = mapped_column(INET())
