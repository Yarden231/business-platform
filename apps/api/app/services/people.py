"""The people directory (docs/api.md §5, docs/security.md §4, ADR-0027).

Every read and write goes through `PersonAccessService.has_full_access`.
`PersonDetail` is built only when that predicate is true, except on create:
the creation response returns detail because the caller authored the values,
and that grant does not persist past the request.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.actions import AuditAction, AuditEntityType
from app.audit.recorder import AuditRecorder
from app.auth.policies import ensure_can_archive_person, ensure_can_edit_person, ensure_role
from app.core.errors import (
    ErrorDetail,
    PersonAlreadyArchivedError,
    PersonIdentifierConflictError,
    PersonNotArchivedError,
    PersonNotFoundError,
    ValidationFailedError,
)
from app.core.pagination import Page, PageRequest
from app.core.time import utc_now
from app.db.uow import transaction
from app.domain.actor import AuthenticatedActor
from app.domain.enums import PersonIdType, UserRole
from app.domain.identifiers import IdentifierPair, mask_identifier, parse_identifier_pair
from app.models.person import Person
from app.repositories.people import PeopleRepository
from app.services.authentication import RequestOrigin
from app.services.person_access import PersonAccessService

_REDACTED: str = "[redacted]"

#: Fields that may appear in an audit `changes` payload with their values.
_AUDIT_VALUE_FIELDS: frozenset[str] = frozenset(
    {
        "first_name",
        "last_name",
        "id_type",
        "email",
        "phone",
        "address",
        "workplace",
        "organization_name",
        "license_number",
        "notes",
        "archived_at",
    }
)


@dataclass(frozen=True, slots=True)
class PersonSummaryView:
    """What an employee may see of a person outside their assigned cases."""

    id: uuid.UUID
    first_name: str
    last_name: str
    organization_name: str | None
    id_number_masked: str | None
    archived_at: datetime | None


@dataclass(frozen=True, slots=True)
class PersonDetailView:
    """The full operational record. Built only after `has_full_access` (or create)."""

    id: uuid.UUID
    first_name: str
    last_name: str
    id_type: PersonIdType | None
    id_number: str | None
    email: str | None
    phone: str | None
    address: str | None
    workplace: str | None
    organization_name: str | None
    license_number: str | None
    notes: str | None
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


PersonReadView = PersonSummaryView | PersonDetailView


class PeopleService:
    """Everything under `/api/v1/people`."""

    def __init__(self, session: AsyncSession) -> None:
        self._db = session
        self._people = PeopleRepository(session)
        self._access = PersonAccessService(session)
        self._audit = AuditRecorder(session)

    async def list_people(
        self,
        actor: AuthenticatedActor,
        *,
        page: PageRequest,
        query: str | None = None,
        archived: bool | None = None,
    ) -> Page[PersonReadView]:
        ensure_role(actor, UserRole.ADMIN, UserRole.EMPLOYEE)
        people, total = await self._people.list_page(page, query=query, archived=archived)
        items: list[PersonReadView] = []
        for person in people:
            items.append(await self._represent(actor, person))
        return Page(items=tuple(items), total=total, page=page.page, page_size=page.page_size)

    async def get_person(self, actor: AuthenticatedActor, person_id: uuid.UUID) -> PersonReadView:
        """Detail when the predicate holds; summary otherwise. Never 403 on a read."""
        ensure_role(actor, UserRole.ADMIN, UserRole.EMPLOYEE)
        person = await self._require_person(person_id)
        return await self._represent(actor, person)

    async def create_person(
        self,
        actor: AuthenticatedActor,
        *,
        first_name: str,
        last_name: str,
        id_type: PersonIdType | None,
        id_number: str | None,
        email: str | None,
        phone: str | None,
        address: str | None,
        workplace: str | None,
        organization_name: str | None,
        license_number: str | None,
        notes: str | None,
        origin: RequestOrigin,
    ) -> PersonDetailView:
        """Create a person. The response is always detail — the caller authored it."""
        ensure_role(actor, UserRole.ADMIN, UserRole.EMPLOYEE)
        identifier = _require_identifier(id_type, id_number)
        fields = _normalised_contact(
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
            address=address,
            workplace=workplace,
            organization_name=organization_name,
            license_number=license_number,
            notes=notes,
        )
        if (
            identifier.id_type is not None
            and identifier.id_number is not None
            and await self._people.get_by_identifier(identifier.id_type, identifier.id_number)
        ):
            raise PersonIdentifierConflictError

        person = Person(
            first_name=fields["first_name"],
            last_name=fields["last_name"],
            id_type=identifier.id_type.value if identifier.id_type is not None else None,
            id_number=identifier.id_number,
            email=fields["email"],
            phone=fields["phone"],
            address=fields["address"],
            workplace=fields["workplace"],
            organization_name=fields["organization_name"],
            license_number=fields["license_number"],
            notes=fields["notes"],
            created_by=actor.id,
        )
        try:
            async with transaction(self._db):
                self._people.add(person)
                await self._audit.record(
                    action=AuditAction.PERSON_CREATED,
                    entity_type=AuditEntityType.PERSON,
                    entity_id=person.id,
                    actor_user_id=actor.id,
                    description="Person created.",
                    metadata=_creation_metadata(identifier),
                    ip_address=origin.ip_address,
                )
        except IntegrityError as exc:
            raise PersonIdentifierConflictError from exc

        await self._db.refresh(person)
        return _detail_of(person)

    async def update_person(
        self,
        actor: AuthenticatedActor,
        person_id: uuid.UUID,
        *,
        fields: dict[str, Any],
        origin: RequestOrigin,
    ) -> PersonDetailView:
        """Apply an allowlist of field changes. Requires the access predicate.

        `fields` is the request body with omitted keys left out, so an explicit
        `null` can clear an optional value and a missing key leaves it alone.
        """
        ensure_role(actor, UserRole.ADMIN, UserRole.EMPLOYEE)
        person = await self._require_person(person_id)
        has_access = await self._access.has_full_access(actor, person.id)
        ensure_can_edit_person(has_full_access=has_access)

        changes: dict[str, Any] = {}
        if "first_name" in fields:
            stripped = _require_name(fields["first_name"], field="first_name")
            if stripped != person.first_name:
                changes["first_name"] = {"before": person.first_name, "after": stripped}
                person.first_name = stripped
        if "last_name" in fields:
            stripped = _require_name(fields["last_name"], field="last_name")
            if stripped != person.last_name:
                changes["last_name"] = {"before": person.last_name, "after": stripped}
                person.last_name = stripped

        identifier_touched = "id_type" in fields or "id_number" in fields
        if identifier_touched:
            if ("id_type" in fields) != ("id_number" in fields):
                missing = "id_number" if "id_type" in fields else "id_type"
                raise ValidationFailedError(
                    details=[ErrorDetail(field=missing, issue="required_with_identifier")]
                )
            parsed = _require_identifier(fields["id_type"], fields["id_number"])
            new_type = parsed.id_type.value if parsed.id_type is not None else None
            new_number = parsed.id_number
            if new_type != person.id_type or new_number != person.id_number:
                if parsed.id_type is not None and parsed.id_number is not None:
                    existing = await self._people.get_by_identifier(
                        parsed.id_type, parsed.id_number
                    )
                    if existing is not None and existing.id != person.id:
                        raise PersonIdentifierConflictError
                if person.id_type != new_type:
                    changes["id_type"] = {"before": person.id_type, "after": new_type}
                if person.id_number != new_number:
                    changes["id_number"] = _redacted_change(person.id_number, new_number)
                person.id_type = new_type
                person.id_number = new_number

        _apply_optional(person, "email", fields, changes, normalise=_normalise_email)
        _apply_optional(person, "phone", fields, changes, normalise=_blank_to_none)
        _apply_optional(person, "address", fields, changes, normalise=_blank_to_none)
        _apply_optional(person, "workplace", fields, changes, normalise=_blank_to_none)
        _apply_optional(person, "organization_name", fields, changes, normalise=_blank_to_none)
        _apply_optional(person, "license_number", fields, changes, normalise=_blank_to_none)
        _apply_optional(person, "notes", fields, changes, normalise=_blank_to_none)

        if not changes:
            return _detail_of(person)

        try:
            async with transaction(self._db):
                await self._audit.record(
                    action=AuditAction.PERSON_UPDATED,
                    entity_type=AuditEntityType.PERSON,
                    entity_id=person.id,
                    actor_user_id=actor.id,
                    description="Person updated.",
                    changes=_audit_changes(changes),
                    ip_address=origin.ip_address,
                )
        except IntegrityError as exc:
            raise PersonIdentifierConflictError from exc

        await self._db.refresh(person)
        return _detail_of(person)

    async def archive_person(
        self,
        actor: AuthenticatedActor,
        person_id: uuid.UUID,
        *,
        origin: RequestOrigin,
    ) -> None:
        ensure_can_archive_person(actor)
        person = await self._require_person(person_id)
        if person.archived_at is not None:
            raise PersonAlreadyArchivedError
        async with transaction(self._db):
            person.archived_at = utc_now()
            await self._audit.record(
                action=AuditAction.PERSON_ARCHIVED,
                entity_type=AuditEntityType.PERSON,
                entity_id=person.id,
                actor_user_id=actor.id,
                description="Person archived.",
                changes={"archived_at": {"before": None, "after": person.archived_at.isoformat()}},
                ip_address=origin.ip_address,
            )

    async def unarchive_person(
        self,
        actor: AuthenticatedActor,
        person_id: uuid.UUID,
        *,
        origin: RequestOrigin,
    ) -> None:
        ensure_can_archive_person(actor)
        person = await self._require_person(person_id)
        if person.archived_at is None:
            raise PersonNotArchivedError
        previous = person.archived_at
        async with transaction(self._db):
            person.archived_at = None
            await self._audit.record(
                action=AuditAction.PERSON_UNARCHIVED,
                entity_type=AuditEntityType.PERSON,
                entity_id=person.id,
                actor_user_id=actor.id,
                description="Person unarchived.",
                changes={"archived_at": {"before": previous.isoformat(), "after": None}},
                ip_address=origin.ip_address,
            )

    async def list_person_cases(
        self,
        actor: AuthenticatedActor,
        person_id: uuid.UUID,
        *,
        page: PageRequest,
    ) -> Page[None]:
        """Cases this person participates in.

        Phase 4 has no cases. The person must exist (so a typo is a 404, not
        an empty page that looks like "no cases"), and the page is always
        empty. Phase 5 will scope the rows to the caller's assignments.
        """
        ensure_role(actor, UserRole.ADMIN, UserRole.EMPLOYEE)
        await self._require_person(person_id)
        return Page(items=(), total=0, page=page.page, page_size=page.page_size)

    async def _require_person(self, person_id: uuid.UUID) -> Person:
        person = await self._people.get(person_id)
        if person is None:
            raise PersonNotFoundError
        return person

    async def _represent(self, actor: AuthenticatedActor, person: Person) -> PersonReadView:
        """The only path that may produce a `PersonDetailView` for a read.

        Create returns `_detail_of` directly because the caller authored the
        values; that grant does not persist past the request (ADR-0027).
        """
        if await self._access.has_full_access(actor, person.id):
            return _detail_of(person)
        return _summary_of(person)


def _detail_of(person: Person) -> PersonDetailView:
    """The one mapping from the ORM row to a full record."""
    return PersonDetailView(
        id=person.id,
        first_name=person.first_name,
        last_name=person.last_name,
        id_type=PersonIdType(person.id_type) if person.id_type is not None else None,
        id_number=person.id_number,
        email=person.email,
        phone=person.phone,
        address=person.address,
        workplace=person.workplace,
        organization_name=person.organization_name,
        license_number=person.license_number,
        notes=person.notes,
        created_by=person.created_by,
        created_at=person.created_at,
        updated_at=person.updated_at,
        archived_at=person.archived_at,
    )


def _summary_of(person: Person) -> PersonSummaryView:
    return PersonSummaryView(
        id=person.id,
        first_name=person.first_name,
        last_name=person.last_name,
        organization_name=person.organization_name,
        id_number_masked=mask_identifier(person.id_number),
        archived_at=person.archived_at,
    )


def _require_identifier(id_type: PersonIdType | None, id_number: str | None) -> IdentifierPair:
    pair, issues = parse_identifier_pair(id_type, id_number)
    if pair is None:
        raise ValidationFailedError(
            details=[ErrorDetail(field=issue.field, issue=issue.issue) for issue in issues]
        )
    return pair


def _require_name(value: str, *, field: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValidationFailedError(details=[ErrorDetail(field=field, issue="blank")])
    return stripped


def _normalise_email(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip().lower()
    if not stripped:
        return None
    if "@" not in stripped or stripped.startswith("@") or stripped.endswith("@"):
        raise ValidationFailedError(details=[ErrorDetail(field="email", issue="invalid")])
    return stripped


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _normalised_contact(
    *,
    first_name: str,
    last_name: str,
    email: str | None,
    phone: str | None,
    address: str | None,
    workplace: str | None,
    organization_name: str | None,
    license_number: str | None,
    notes: str | None,
) -> dict[str, str | None]:
    return {
        "first_name": _require_name(first_name, field="first_name"),
        "last_name": _require_name(last_name, field="last_name"),
        "email": _normalise_email(email),
        "phone": _blank_to_none(phone),
        "address": _blank_to_none(address),
        "workplace": _blank_to_none(workplace),
        "organization_name": _blank_to_none(organization_name),
        "license_number": _blank_to_none(license_number),
        "notes": _blank_to_none(notes),
    }


def _apply_optional(
    person: Person,
    field: str,
    fields: dict[str, Any],
    changes: dict[str, Any],
    *,
    normalise: Callable[[str | None], str | None],
) -> None:
    if field not in fields:
        return
    value = fields[field]
    normalised = normalise(value) if value is None or isinstance(value, str) else value
    current = getattr(person, field)
    if normalised != current:
        changes[field] = {"before": current, "after": normalised}
        setattr(person, field, normalised)


def _redacted_change(before: str | None, after: str | None) -> dict[str, str | None]:
    """Prove the identifier changed without writing the identifier (docs/security.md §7)."""
    return {
        "before": _REDACTED if before is not None else None,
        "after": _REDACTED if after is not None else None,
    }


def _audit_changes(changes: dict[str, Any]) -> dict[str, Any]:
    """Drop anything that is not on the allowlist; `id_number` is already redacted."""
    allowed = {key: value for key, value in changes.items() if key in _AUDIT_VALUE_FIELDS}
    if "id_number" in changes:
        allowed["id_number"] = changes["id_number"]
    return allowed


def _creation_metadata(identifier: IdentifierPair) -> dict[str, Any]:
    """Record that an identifier was supplied, never the identifier itself."""
    if identifier.id_type is None:
        return {"identifier_present": False}
    return {"identifier_present": True, "id_type": identifier.id_type.value}
