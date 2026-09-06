"""Reads and writes over `users`."""

from __future__ import annotations

import uuid

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import PageRequest
from app.domain.enums import UserRole
from app.models.user import User


def normalize_email(email: str) -> str:
    """The one definition of "the same email address" in this codebase.

    `users.email` carries a `CHECK (email = lower(btrim(email)))`, so an
    un-normalised insert is refused by PostgreSQL rather than quietly creating a
    second account for the same person. This function is what keeps the
    application on the right side of that constraint, and it is applied to the
    login identifier as well as to stored values.
    """
    return email.strip().lower()


class UserRepository:
    """Staff accounts."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, user: User) -> None:
        self._session.add(user)

    async def get(self, user_id: uuid.UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        """Look a user up by login identifier. `email` is normalised here, not by the caller."""
        found: User | None = await self._session.scalar(
            select(User).where(User.email == normalize_email(email))
        )
        return found

    async def exists_with_email(self, email: str) -> bool:
        found = await self._session.scalar(
            select(User.id).where(User.email == normalize_email(email)).limit(1)
        )
        return found is not None

    async def count_active_admins(self, *, excluding: uuid.UUID | None = None) -> int:
        """How many active admins remain — the guard against locking the firm out.

        `excluding` answers "…if this one were removed", which is what the
        deactivation and role-change paths need to ask before they act.
        """
        statement = select(func.count(User.id)).where(
            User.role == UserRole.ADMIN.value,
            User.deactivated_at.is_(None),
        )
        if excluding is not None:
            statement = statement.where(User.id != excluding)
        return await self._session.scalar(statement) or 0

    async def list_page(
        self,
        page: PageRequest,
        *,
        query: str | None = None,
        role: UserRole | None = None,
        is_active: bool | None = None,
    ) -> tuple[tuple[User, ...], int]:
        """One page of users plus the unpaginated total, for `GET /api/v1/users`."""
        filtered = self._filtered(query=query, role=role, is_active=is_active)
        total = await self._session.scalar(select(func.count()).select_from(filtered.subquery()))
        rows = await self._session.scalars(
            filtered.order_by(User.full_name, User.id).offset(page.offset).limit(page.limit)
        )
        return tuple(rows), total or 0

    async def list_directory(self) -> tuple[User, ...]:
        """Active staff only, name-ordered, for assignee pickers (docs/api.md §5)."""
        rows = await self._session.scalars(
            select(User).where(User.deactivated_at.is_(None)).order_by(User.full_name, User.id)
        )
        return tuple(rows)

    def _filtered(
        self,
        *,
        query: str | None,
        role: UserRole | None,
        is_active: bool | None,
    ) -> Select[tuple[User]]:
        statement = select(User)
        if query:
            pattern = f"%{_escape_like(query.strip())}%"
            statement = statement.where(
                or_(
                    User.full_name.ilike(pattern, escape="\\"),
                    User.email.ilike(pattern, escape="\\"),
                )
            )
        if role is not None:
            statement = statement.where(User.role == role.value)
        if is_active is not None:
            statement = statement.where(
                User.deactivated_at.is_(None) if is_active else User.deactivated_at.is_not(None)
            )
        return statement


def _escape_like(value: str) -> str:
    """Neutralise the `LIKE` wildcards so a search term cannot become a pattern.

    Without this, a query of `%` matches every user and `_` matches any single
    character — a small thing here, and the same bug that turns a search box
    into a data-extraction tool on a table that holds personal data.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
