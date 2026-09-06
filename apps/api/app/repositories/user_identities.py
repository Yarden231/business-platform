"""Reads and writes over `user_identities`.

Release 1 only ever touches `PASSWORD` rows. The provider is still passed and
filtered on explicitly rather than assumed, because a `MICROSOFT_ENTRA` row for
the same user is an insert away (ADR-0006) and a query that silently matched
"the user's identity" would then match the wrong one.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import IdentityProvider
from app.models.user_identity import UserIdentity


class UserIdentityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, identity: UserIdentity) -> None:
        self._session.add(identity)

    async def get_by_subject(
        self, *, provider: IdentityProvider, subject: str
    ) -> UserIdentity | None:
        """The identity a login identifier resolves to.

        One indexed lookup on `UNIQUE (provider, provider_subject)`.
        """
        found: UserIdentity | None = await self._session.scalar(
            select(UserIdentity).where(
                UserIdentity.provider == provider.value,
                UserIdentity.provider_subject == subject,
            )
        )
        return found

    async def get_for_user(
        self, *, user_id: uuid.UUID, provider: IdentityProvider
    ) -> UserIdentity | None:
        """This user's identity with one provider, via `UNIQUE (user_id, provider)`."""
        found: UserIdentity | None = await self._session.scalar(
            select(UserIdentity).where(
                UserIdentity.user_id == user_id,
                UserIdentity.provider == provider.value,
            )
        )
        return found
