"""The people directory.

Creates the central `people` registry: a reusable identity/contact record with
a typed identifier pair (Q7 / ADR-0040). Case participation is Phase 5; this
table does not encode case roles.

Revision ID: 0002
Revises: 0001
Created: 2026-09-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "people",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("first_name", sa.String(length=200), nullable=False),
        sa.Column("last_name", sa.String(length=200), nullable=False),
        sa.Column("id_type", sa.String(length=32), nullable=True),
        sa.Column("id_number", sa.String(length=64), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("phone", sa.String(length=64), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("workplace", sa.String(length=200), nullable=True),
        sa.Column("organization_name", sa.String(length=200), nullable=True),
        sa.Column("license_number", sa.String(length=64), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("btrim(first_name) <> ''", name="first_name_not_blank"),
        sa.CheckConstraint("btrim(last_name) <> ''", name="last_name_not_blank"),
        sa.CheckConstraint("(id_type IS NULL) = (id_number IS NULL)", name="identifier_pair"),
        sa.CheckConstraint(
            "id_type IS NULL OR id_type IN ('ISRAELI_ID', 'PASSPORT', 'FOREIGN_ID')",
            name="id_type",
        ),
        sa.CheckConstraint(
            "email IS NULL OR (email = lower(btrim(email)) AND email <> '')",
            name="email_normalized",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name="fk_people_created_by_users", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_people"),
        sa.UniqueConstraint("id_type", "id_number", name="uq_people_id_type_id_number"),
    )
    op.create_index("ix_people_archived_at", "people", ["archived_at"])
    op.execute(
        "CREATE INDEX ix_people_first_name_trgm ON people USING gin (first_name gin_trgm_ops)"
    )
    op.execute("CREATE INDEX ix_people_last_name_trgm ON people USING gin (last_name gin_trgm_ops)")
    op.execute(
        "CREATE INDEX ix_people_organization_name_trgm "
        "ON people USING gin (organization_name gin_trgm_ops)"
    )
    op.execute("CREATE INDEX ix_people_id_number_trgm ON people USING gin (id_number gin_trgm_ops)")


def downgrade() -> None:
    op.drop_index("ix_people_id_number_trgm", table_name="people")
    op.drop_index("ix_people_organization_name_trgm", table_name="people")
    op.drop_index("ix_people_last_name_trgm", table_name="people")
    op.drop_index("ix_people_first_name_trgm", table_name="people")
    op.drop_index("ix_people_archived_at", table_name="people")
    op.drop_table("people")
