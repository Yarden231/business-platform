"""The single person-access predicate (ADR-0027).

`has_full_access` governs representation (`PersonDetail` vs `PersonSummary`),
detail reads and `PATCH` rights. One function, so those three cannot drift.

Phase 4-safe: cases, participants and assignments do not exist yet. An
`EMPLOYEE` therefore cannot honestly hold full access — there is no
participation or assignment row that could grant it. `ADMIN` always has full
access. Phase 5 will replace the employee branch with an `EXISTS` over
active participation in a case currently assigned to the actor.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.actor import AuthenticatedActor
from app.domain.enums import UserRole


class PersonAccessService:
    """Resolves whether an actor may see and edit a person's full record."""

    def __init__(self, session: AsyncSession) -> None:
        # Held for Phase 5, which will query `case_participants` / `case_assignments`
        # through this same session. Unused in Phase 4 on purpose.
        self._session = session

    async def has_full_access(self, actor: AuthenticatedActor, person_id: uuid.UUID) -> bool:
        """True for any `ADMIN`. False for every `EMPLOYEE` until Phase 5.

        `person_id` is accepted now so the signature does not change when the
        employee branch starts consulting participation. It is not used while
        there are no cases to participate in.
        """
        _ = (self._session, person_id)
        return actor.role is UserRole.ADMIN
