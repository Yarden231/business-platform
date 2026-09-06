"""Reads and writes over `people`."""

from __future__ import annotations

import uuid

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import PageRequest
from app.domain.enums import PersonIdType
from app.models.person import Person


class PeopleRepository:
    """The central person registry."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, person: Person) -> None:
        self._session.add(person)

    async def get(self, person_id: uuid.UUID) -> Person | None:
        return await self._session.get(Person, person_id)

    async def get_by_identifier(self, id_type: PersonIdType, id_number: str) -> Person | None:
        found: Person | None = await self._session.scalar(
            select(Person).where(
                Person.id_type == id_type.value,
                Person.id_number == id_number,
            )
        )
        return found

    async def list_page(
        self,
        page: PageRequest,
        *,
        query: str | None = None,
        archived: bool | None = None,
    ) -> tuple[tuple[Person, ...], int]:
        """One page plus the unpaginated total, for `GET /api/v1/people`."""
        filtered = self._filtered(query=query, archived=archived)
        total = await self._session.scalar(select(func.count()).select_from(filtered.subquery()))
        rows = await self._session.scalars(
            filtered.order_by(Person.last_name, Person.first_name, Person.id)
            .offset(page.offset)
            .limit(page.limit)
        )
        return tuple(rows), total or 0

    def _filtered(self, *, query: str | None, archived: bool | None) -> Select[tuple[Person]]:
        statement = select(Person)
        if archived is None or archived is False:
            statement = statement.where(Person.archived_at.is_(None))
        elif archived is True:
            statement = statement.where(Person.archived_at.is_not(None))
        if query:
            pattern = f"%{_escape_like(query.strip())}%"
            statement = statement.where(
                or_(
                    Person.first_name.ilike(pattern, escape="\\"),
                    Person.last_name.ilike(pattern, escape="\\"),
                    Person.organization_name.ilike(pattern, escape="\\"),
                    Person.id_number.ilike(pattern, escape="\\"),
                )
            )
        return statement


def _escape_like(value: str) -> str:
    """Neutralise `LIKE` wildcards so a search term cannot become a pattern."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
