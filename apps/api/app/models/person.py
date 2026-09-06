"""The central person registry (docs/domain-model.md §4).

A person is a reusable identity/contact record — a party, a lawyer, a court
contact. Role on a case is a property of participation (Phase 5), not of this
row. Organizations are not people; there is no `COMPANY_NUMBER` identifier.
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
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.enums import PersonIdType
from app.domain.identifiers import IDENTIFIER_MAX_LENGTH
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

_ID_TYPE_VALUES = ", ".join(f"'{member.value}'" for member in PersonIdType)


class Person(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "people"
    __table_args__ = (
        CheckConstraint("btrim(first_name) <> ''", name="first_name_not_blank"),
        CheckConstraint("btrim(last_name) <> ''", name="last_name_not_blank"),
        # Both present or both absent (Q7 / ADR-0040). Equality of the two
        # IS NULL predicates is the shortest way to write that.
        CheckConstraint(
            "(id_type IS NULL) = (id_number IS NULL)",
            name="identifier_pair",
        ),
        CheckConstraint(
            f"id_type IS NULL OR id_type IN ({_ID_TYPE_VALUES})",
            name="id_type",
        ),
        CheckConstraint(
            "email IS NULL OR (email = lower(btrim(email)) AND email <> '')",
            name="email_normalized",
        ),
        UniqueConstraint("id_type", "id_number"),
        Index(
            "ix_people_first_name_trgm",
            "first_name",
            postgresql_using="gin",
            postgresql_ops={"first_name": "gin_trgm_ops"},
        ),
        Index(
            "ix_people_last_name_trgm",
            "last_name",
            postgresql_using="gin",
            postgresql_ops={"last_name": "gin_trgm_ops"},
        ),
        Index(
            "ix_people_organization_name_trgm",
            "organization_name",
            postgresql_using="gin",
            postgresql_ops={"organization_name": "gin_trgm_ops"},
        ),
        Index(
            "ix_people_id_number_trgm",
            "id_number",
            postgresql_using="gin",
            postgresql_ops={"id_number": "gin_trgm_ops"},
        ),
        Index("ix_people_archived_at", "archived_at"),
    )

    first_name: Mapped[str] = mapped_column(String(200), nullable=False)
    last_name: Mapped[str] = mapped_column(String(200), nullable=False)
    id_type: Mapped[str | None] = mapped_column(String(32))
    id_number: Mapped[str | None] = mapped_column(String(IDENTIFIER_MAX_LENGTH))
    email: Mapped[str | None] = mapped_column(String(320))
    #: Stored as entered (trimmed). Search is on name, identifier and organisation.
    phone: Mapped[str | None] = mapped_column(String(64))
    address: Mapped[str | None] = mapped_column(Text())
    workplace: Mapped[str | None] = mapped_column(String(200))
    organization_name: Mapped[str | None] = mapped_column(String(200))
    license_number: Mapped[str | None] = mapped_column(String(64))
    notes: Mapped[str | None] = mapped_column(Text())
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
