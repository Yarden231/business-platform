"""Infrastructure tables: users, identities, sessions and the audit log

Creates the platform every later phase builds on, and nothing else. `people`,
`cases` and the document tables belong to the phases that use them
(docs/roadmap.md).

Three things here are worth reading rather than skimming:

* `activity_log.case_id` has **no** foreign key. `cases` does not exist yet, and
  inventing it early would be worse than waiting; Phase 5 adds the constraint
  with a one-line `ALTER TABLE` (ADR-0030).
* `activity_log` is protected by a trigger, not by a convention. `UPDATE`,
  `DELETE` and `TRUNCATE` all raise (ADR-0010).
* Every foreign key is `ON DELETE RESTRICT`. Nothing in this schema is
  deletable, so a stray `DELETE` fails instead of cascading through history.

Check constraints are given their bare name (`role`, not `ck_users_role`): the
`ck_%(table_name)s_%(constraint_name)s` convention in `app.db.base` supplies the
prefix, exactly as it does for the models, and passing a prefixed name here
would produce `ck_users_ck_users_role` in the database.

Revision ID: 0001
Revises:
Created: 2026-09-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: Generic because `case_status_history` reuses it in Phase 5. `0A000` is
#: `feature_not_supported`, which is the honest SQLSTATE for "this table does
#: not support that operation".
_APPEND_ONLY_GUARD = """
CREATE FUNCTION append_only_guard() RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'Table % is append-only; % is not permitted',
        TG_TABLE_NAME, TG_OP
        USING ERRCODE = '0A000';
END;
$$
"""


def upgrade() -> None:
    # Trigram search over Hebrew names and partial ID numbers (ADR-0024). The
    # indexes that use it arrive with `people` in Phase 4; the extension is
    # enabled here so no later migration has to be the one that needs the
    # elevated privilege.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    _create_users()
    _create_user_identities()
    _create_sessions()
    _create_activity_log()

    op.execute(_APPEND_ONLY_GUARD)
    op.execute(
        """
        CREATE TRIGGER activity_log_append_only
            BEFORE UPDATE OR DELETE ON activity_log
            FOR EACH ROW EXECUTE FUNCTION append_only_guard()
        """
    )
    # Row triggers do not fire for TRUNCATE, so without this the table could
    # still be emptied in one statement.
    op.execute(
        """
        CREATE TRIGGER activity_log_append_only_truncate
            BEFORE TRUNCATE ON activity_log
            FOR EACH STATEMENT EXECUTE FUNCTION append_only_guard()
        """
    )


def downgrade() -> None:
    op.drop_table("activity_log")
    op.drop_table("sessions")
    op.drop_table("user_identities")
    op.drop_table("users")
    # The triggers went with their table; the function did not.
    op.execute("DROP FUNCTION IF EXISTS append_only_guard()")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")


def _create_users() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column(
            "must_change_password", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
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
        sa.CheckConstraint("email = lower(btrim(email)) AND email <> ''", name="email_normalized"),
        sa.CheckConstraint("btrim(full_name) <> ''", name="full_name_not_blank"),
        sa.CheckConstraint("role IN ('ADMIN', 'EMPLOYEE')", name="role"),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name="fk_users_created_by_users", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )


def _create_user_identities() -> None:
    op.create_table(
        "user_identities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_subject", sa.String(length=320), nullable=False),
        sa.Column("secret_hash", sa.Text(), nullable=True),
        sa.Column("secret_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "failed_attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "failed_attempt_count >= 0",
            name="failed_attempt_count_non_negative",
        ),
        sa.CheckConstraint(
            "provider <> 'PASSWORD' OR secret_hash IS NOT NULL",
            name="password_requires_secret",
        ),
        sa.CheckConstraint("provider IN ('PASSWORD', 'MICROSOFT_ENTRA')", name="provider"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_user_identities_user_id_users", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_identities"),
        sa.UniqueConstraint(
            "provider", "provider_subject", name="uq_user_identities_provider_provider_subject"
        ),
        sa.UniqueConstraint("user_id", "provider", name="uq_user_identities_user_id_provider"),
    )
    op.create_index("ix_user_identities_user_id", "user_identities", ["user_id"])


def _create_sessions() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "issued_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.CheckConstraint("expires_at > issued_at", name="expires_after_issued"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_sessions_user_id_users", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sessions"),
        sa.UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
    )
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])
    op.create_index("ix_sessions_user_id_revoked_at", "sessions", ["user_id", "revoked_at"])


def _create_activity_log() -> None:
    op.create_table(
        "activity_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        # No foreign key: `cases` does not exist yet (ADR-0030).
        sa.Column("case_id", sa.Uuid(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("changes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.CheckConstraint("btrim(action) <> ''", name="action_not_blank"),
        sa.CheckConstraint("btrim(description) <> ''", name="description_not_blank"),
        sa.CheckConstraint("btrim(entity_type) <> ''", name="entity_type_not_blank"),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_activity_log_actor_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_activity_log"),
    )
    op.create_index("ix_activity_log_action_occurred_at", "activity_log", ["action", "occurred_at"])
    op.create_index(
        "ix_activity_log_actor_user_id_occurred_at",
        "activity_log",
        ["actor_user_id", "occurred_at"],
    )
    op.create_index(
        "ix_activity_log_case_id_occurred_at", "activity_log", ["case_id", "occurred_at"]
    )
    op.create_index(
        "ix_activity_log_entity_type_entity_id", "activity_log", ["entity_type", "entity_id"]
    )
    op.create_index("ix_activity_log_occurred_at", "activity_log", ["occurred_at"])
