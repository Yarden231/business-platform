"""Test factories for business entities.

Phase 1 deferred these: four infrastructure tables did not need a factory
layer. `people` is the first entity with enough optional fields to warrant
one (docs/roadmap.md, Phase 1).
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import PersonIdType
from app.models.person import Person


async def create_person(
    session: AsyncSession,
    *,
    created_by: uuid.UUID,
    first_name: str = "דנה",
    last_name: str = "כהן",
    id_type: PersonIdType | None = None,
    id_number: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    address: str | None = None,
    workplace: str | None = None,
    organization_name: str | None = None,
    license_number: str | None = None,
    notes: str | None = None,
    archived: bool = False,
) -> Person:
    """A person row, flushed so its timestamps are PostgreSQL's."""
    from app.core.time import utc_now

    person = Person(
        first_name=first_name,
        last_name=last_name,
        id_type=id_type.value if id_type is not None else None,
        id_number=id_number,
        email=email.strip().lower() if email else None,
        phone=phone,
        address=address,
        workplace=workplace,
        organization_name=organization_name,
        license_number=license_number,
        notes=notes,
        created_by=created_by,
        archived_at=utc_now() if archived else None,
    )
    session.add(person)
    await session.flush()
    return person


#: A known-valid Israeli ID (checksum 0). Used wherever a test needs a real number.
VALID_ISRAELI_ID = "123456782"
VALID_ISRAELI_ID_OTHER = "000000018"
