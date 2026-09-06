"""Enumerations stored as `TEXT` with a `CHECK` constraint (ADR-0023).

Each of these is mirrored by a check constraint on its column, so an invalid
value is refused by PostgreSQL and not only by Python. Adding a value is a
one-line constraint migration plus a member here.
"""

from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    """Release 1 has exactly two staff roles (docs/security.md §4).

    `CLIENT` and `LAWYER` portals are a later release, and arrive as a
    `user_roles` table rather than as members here.
    """

    ADMIN = "ADMIN"
    EMPLOYEE = "EMPLOYEE"


class IdentityProvider(StrEnum):
    """How a user proves who they are (ADR-0006).

    `MICROSOFT_ENTRA` exists in the schema from the first migration so that
    federating later is an insert rather than a migration of `users`. No Entra
    code exists in Release 1.
    """

    PASSWORD = "PASSWORD"  # noqa: S105 - a provider name, not a secret
    MICROSOFT_ENTRA = "MICROSOFT_ENTRA"


class PersonIdType(StrEnum):
    """How a person's official identifier is classified (Q7 / ADR-0040).

    Organizations are not people: `COMPANY_NUMBER` is deliberately absent.
    A person may have no identifier at all — both `id_type` and `id_number`
    are then NULL together.
    """

    ISRAELI_ID = "ISRAELI_ID"
    PASSPORT = "PASSPORT"
    FOREIGN_ID = "FOREIGN_ID"
