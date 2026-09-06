"""The people directory (docs/api.md §5, ADR-0027, Q7 / ADR-0040).

Authorization that depends on case participation waits for Phase 5: those
tables do not exist, and inventing a grant would be a fake. Phase 4 asserts
the honest subset — admin full access, employee summary-only, create-then-no
PATCH, archive is ADMIN-only — and the predicate that Phase 5 will extend.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.actions import AuditAction
from app.domain.enums import PersonIdType
from app.models.activity_log import ActivityLog
from app.models.user import User
from tests.support.accounts import (
    ADMIN_PASSWORD,
    EMPLOYEE_PASSWORD,
    create_admin,
    create_employee,
    csrf_headers,
    log_in,
)
from tests.support.factories import VALID_ISRAELI_ID, VALID_ISRAELI_ID_OTHER, create_person

_DETAIL_FIELDS = {
    "representation",
    "id",
    "first_name",
    "last_name",
    "id_type",
    "id_number",
    "email",
    "phone",
    "address",
    "workplace",
    "organization_name",
    "license_number",
    "notes",
    "created_by",
    "created_at",
    "updated_at",
    "archived_at",
}
_SUMMARY_FIELDS = {
    "representation",
    "id",
    "first_name",
    "last_name",
    "organization_name",
    "id_number_masked",
    "archived_at",
}
_FORBIDDEN_ON_SUMMARY = {
    "id_number",
    "id_type",
    "email",
    "phone",
    "address",
    "workplace",
    "license_number",
    "notes",
    "created_by",
}


@pytest.fixture
async def admin(db_client: AsyncClient, db_session: AsyncSession) -> tuple[AsyncClient, str, User]:
    user = await create_admin(db_session, email="admin@example.com")
    token = await log_in(db_client, email="admin@example.com", password=ADMIN_PASSWORD)
    return db_client, token, user


@pytest.fixture
async def employee(
    db_client: AsyncClient, db_session: AsyncSession
) -> tuple[AsyncClient, str, User]:
    user = await create_employee(db_session, email="employee@example.com")
    token = await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)
    return db_client, token, user


def _create_body(**overrides: object) -> dict[str, Any]:
    body: dict[str, Any] = {"first_name": "דנה", "last_name": "לוי"}
    body.update(overrides)
    return body


async def _audit(session: AsyncSession, action: AuditAction) -> ActivityLog | None:
    found: ActivityLog | None = await session.scalar(
        select(ActivityLog).where(ActivityLog.action == action.value)
    )
    return found


class TestCreate:
    async def test_an_admin_creates_a_person_and_receives_detail(
        self, admin: tuple[AsyncClient, str, User]
    ) -> None:
        client, token, actor = admin

        response = await client.post(
            "/api/v1/people",
            json=_create_body(
                id_type="ISRAELI_ID",
                id_number=VALID_ISRAELI_ID,
                email="dana@example.com",
                organization_name="משרד לוי",
            ),
            headers=csrf_headers(token),
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["representation"] == "DETAIL"
        assert set(body) == _DETAIL_FIELDS
        assert body["id_number"] == VALID_ISRAELI_ID
        assert body["id_type"] == "ISRAELI_ID"
        assert body["email"] == "dana@example.com"
        assert body["created_by"] == str(actor.id)

    async def test_a_person_may_have_no_identifier(
        self, admin: tuple[AsyncClient, str, User]
    ) -> None:
        client, token, _ = admin

        first = await client.post(
            "/api/v1/people", json=_create_body(), headers=csrf_headers(token)
        )
        second = await client.post(
            "/api/v1/people",
            json=_create_body(first_name="נועה", last_name="גולן"),
            headers=csrf_headers(token),
        )

        assert first.status_code == 201
        assert first.json()["id_type"] is None
        assert first.json()["id_number"] is None
        assert second.status_code == 201

    async def test_a_type_without_a_number_is_refused(
        self, admin: tuple[AsyncClient, str, User]
    ) -> None:
        client, token, _ = admin

        response = await client.post(
            "/api/v1/people",
            json=_create_body(id_type="PASSPORT"),
            headers=csrf_headers(token),
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    async def test_a_number_without_a_type_is_refused(
        self, admin: tuple[AsyncClient, str, User]
    ) -> None:
        client, token, _ = admin

        response = await client.post(
            "/api/v1/people",
            json=_create_body(id_number=VALID_ISRAELI_ID),
            headers=csrf_headers(token),
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    async def test_company_number_is_not_an_identifier_type(
        self, admin: tuple[AsyncClient, str, User]
    ) -> None:
        client, token, _ = admin

        response = await client.post(
            "/api/v1/people",
            json=_create_body(id_type="COMPANY_NUMBER", id_number="514123456"),
            headers=csrf_headers(token),
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    async def test_an_invalid_israeli_id_is_refused(
        self, admin: tuple[AsyncClient, str, User]
    ) -> None:
        client, token, _ = admin

        response = await client.post(
            "/api/v1/people",
            json=_create_body(id_type="ISRAELI_ID", id_number="123456780"),
            headers=csrf_headers(token),
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"
        assert response.json()["error"]["details"] == [
            {"field": "id_number", "issue": "israeli_id_checksum"}
        ]
        assert "123456780" not in response.text

    async def test_a_duplicate_identifier_is_a_conflict(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, token, actor = admin
        await create_person(
            db_session,
            created_by=actor.id,
            id_type=PersonIdType.ISRAELI_ID,
            id_number=VALID_ISRAELI_ID,
        )

        response = await client.post(
            "/api/v1/people",
            json=_create_body(id_type="ISRAELI_ID", id_number=VALID_ISRAELI_ID),
            headers=csrf_headers(token),
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "PERSON_IDENTIFIER_CONFLICT"

    async def test_the_same_number_under_a_different_type_is_allowed(
        self, admin: tuple[AsyncClient, str, User]
    ) -> None:
        client, token, _ = admin
        first = await client.post(
            "/api/v1/people",
            json=_create_body(id_type="PASSPORT", id_number="AB1234567"),
            headers=csrf_headers(token),
        )
        second = await client.post(
            "/api/v1/people",
            json=_create_body(
                first_name="נועה",
                last_name="גולן",
                id_type="FOREIGN_ID",
                id_number="AB1234567",
            ),
            headers=csrf_headers(token),
        )

        assert first.status_code == 201
        assert second.status_code == 201

    async def test_create_is_audited_without_the_identifier(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, token, _ = admin

        await client.post(
            "/api/v1/people",
            json=_create_body(id_type="ISRAELI_ID", id_number=VALID_ISRAELI_ID),
            headers=csrf_headers(token),
        )

        entry = await _audit(db_session, AuditAction.PERSON_CREATED)
        assert entry is not None
        assert VALID_ISRAELI_ID not in (entry.description or "")
        assert VALID_ISRAELI_ID not in str(entry.event_metadata)
        assert entry.event_metadata["identifier_present"] is True
        assert entry.event_metadata["id_type"] == "ISRAELI_ID"

    async def test_an_employee_may_create_and_receives_detail(
        self, employee: tuple[AsyncClient, str, User]
    ) -> None:
        client, token, _ = employee

        response = await client.post(
            "/api/v1/people",
            json=_create_body(email="created@example.com", phone="050-0000000"),
            headers=csrf_headers(token),
        )

        assert response.status_code == 201
        assert response.json()["representation"] == "DETAIL"
        assert response.json()["email"] == "created@example.com"


class TestReadAndSearch:
    async def test_an_admin_list_returns_detail(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, _token, actor = admin
        await create_person(
            db_session,
            created_by=actor.id,
            id_type=PersonIdType.ISRAELI_ID,
            id_number=VALID_ISRAELI_ID,
            email="hidden@example.com",
        )

        response = await client.get("/api/v1/people")

        assert response.status_code == 200
        item = response.json()["items"][0]
        assert item["representation"] == "DETAIL"
        assert set(item) == _DETAIL_FIELDS
        assert item["id_number"] == VALID_ISRAELI_ID
        assert item["email"] == "hidden@example.com"

    async def test_an_employee_list_returns_summary_only(
        self, employee: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, _token, actor = employee
        await create_person(
            db_session,
            created_by=actor.id,
            first_name="רות",
            last_name="מזרחי",
            id_type=PersonIdType.ISRAELI_ID,
            id_number=VALID_ISRAELI_ID,
            email="secret@example.com",
            phone="050-1111111",
            address="תל אביב",
            workplace="בנק",
            notes="לא לחשוף",
            organization_name="משרד מזרחי",
        )

        response = await client.get("/api/v1/people")

        assert response.status_code == 200
        item = response.json()["items"][0]
        assert item["representation"] == "SUMMARY"
        assert set(item) == _SUMMARY_FIELDS
        assert item["id_number_masked"] == "******782"
        assert item["organization_name"] == "משרד מזרחי"
        for field in _FORBIDDEN_ON_SUMMARY:
            assert field not in item
        assert VALID_ISRAELI_ID not in response.text
        assert "secret@example.com" not in response.text
        assert "לא לחשוף" not in response.text

    async def test_an_employee_read_outside_cases_is_summary_not_an_error(
        self, employee: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, _token, actor = employee
        person = await create_person(
            db_session,
            created_by=actor.id,
            id_type=PersonIdType.PASSPORT,
            id_number="AB1234567",
            email="out@example.com",
        )

        response = await client.get(f"/api/v1/people/{person.id}")

        assert response.status_code == 200
        assert response.json()["representation"] == "SUMMARY"
        assert "email" not in response.json()
        assert "AB1234567" not in response.text

    async def test_search_matches_name_organisation_and_identifier(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, _token, actor = admin
        await create_person(db_session, created_by=actor.id, first_name="אלון", last_name="ברק")
        await create_person(
            db_session,
            created_by=actor.id,
            first_name="מיכל",
            last_name="שמש",
            organization_name="עיריית חיפה",
        )
        await create_person(
            db_session,
            created_by=actor.id,
            first_name="נועה",
            last_name="גולן",
            id_type=PersonIdType.ISRAELI_ID,
            id_number=VALID_ISRAELI_ID,
        )

        by_name = await client.get("/api/v1/people", params={"query": "ברק"})
        by_org = await client.get("/api/v1/people", params={"query": "חיפה"})
        by_id = await client.get("/api/v1/people", params={"query": "456782"})

        assert {item["last_name"] for item in by_name.json()["items"]} == {"ברק"}
        assert {item["last_name"] for item in by_org.json()["items"]} == {"שמש"}
        assert {item["last_name"] for item in by_id.json()["items"]} == {"גולן"}

    async def test_archived_people_are_hidden_from_the_default_list(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, _token, actor = admin
        await create_person(db_session, created_by=actor.id, last_name="פעיל")
        archived = await create_person(
            db_session, created_by=actor.id, last_name="בארכיון", archived=True
        )

        default = await client.get("/api/v1/people")
        only_archived = await client.get("/api/v1/people", params={"archived": "true"})
        still_readable = await client.get(f"/api/v1/people/{archived.id}")

        assert [item["last_name"] for item in default.json()["items"]] == ["פעיל"]
        assert [item["last_name"] for item in only_archived.json()["items"]] == ["בארכיון"]
        assert still_readable.status_code == 200

    async def test_a_missing_person_is_not_found(
        self, admin: tuple[AsyncClient, str, User]
    ) -> None:
        client, _token, _ = admin

        response = await client.get(f"/api/v1/people/{uuid.uuid4()}")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "PERSON_NOT_FOUND"

    async def test_person_cases_are_an_empty_page(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, _token, actor = admin
        person = await create_person(db_session, created_by=actor.id)

        response = await client.get(f"/api/v1/people/{person.id}/cases")

        assert response.status_code == 200
        assert response.json() == {"items": [], "total": 0, "page": 1, "page_size": 25}


class TestUpdate:
    async def test_an_admin_can_edit_any_person(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, token, actor = admin
        person = await create_person(db_session, created_by=actor.id, last_name="ישן")

        response = await client.patch(
            f"/api/v1/people/{person.id}",
            json={"last_name": "חדש", "email": "new@example.com"},
            headers=csrf_headers(token),
        )

        assert response.status_code == 200
        assert response.json()["last_name"] == "חדש"
        assert response.json()["email"] == "new@example.com"

    async def test_an_employee_cannot_patch_even_a_person_they_created(
        self, employee: tuple[AsyncClient, str, User]
    ) -> None:
        client, token, _ = employee
        created = await client.post(
            "/api/v1/people", json=_create_body(), headers=csrf_headers(token)
        )
        person_id = created.json()["id"]

        response = await client.patch(
            f"/api/v1/people/{person_id}",
            json={"last_name": "תיקון"},
            headers=csrf_headers(token),
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PERSON_ACCESS_DENIED"
        unchanged = await client.get(f"/api/v1/people/{person_id}")
        assert unchanged.json()["last_name"] == "לוי"

    async def test_an_employee_patch_leaves_the_row_untouched(
        self, employee: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, token, actor = employee
        person = await create_person(
            db_session, created_by=actor.id, last_name="מקורי", notes="סוד"
        )

        await client.patch(
            f"/api/v1/people/{person.id}",
            json={"last_name": "פריצה", "notes": "נחשף"},
            headers=csrf_headers(token),
        )

        await db_session.refresh(person)
        assert person.last_name == "מקורי"
        assert person.notes == "סוד"

    async def test_updating_an_identifier_is_redacted_in_audit(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, token, actor = admin
        person = await create_person(
            db_session,
            created_by=actor.id,
            id_type=PersonIdType.ISRAELI_ID,
            id_number=VALID_ISRAELI_ID,
        )

        response = await client.patch(
            f"/api/v1/people/{person.id}",
            json={"id_type": "ISRAELI_ID", "id_number": VALID_ISRAELI_ID_OTHER},
            headers=csrf_headers(token),
        )

        assert response.status_code == 200
        entry = await _audit(db_session, AuditAction.PERSON_UPDATED)
        assert entry is not None
        assert entry.changes == {"id_number": {"before": "[redacted]", "after": "[redacted]"}}
        assert VALID_ISRAELI_ID not in str(entry.changes)
        assert VALID_ISRAELI_ID_OTHER not in str(entry.changes)


class TestArchive:
    async def test_an_admin_can_archive_and_unarchive(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, token, actor = admin
        person = await create_person(db_session, created_by=actor.id)

        archived = await client.post(
            f"/api/v1/people/{person.id}/archive", headers=csrf_headers(token)
        )
        assert archived.status_code == 204
        await db_session.refresh(person)
        assert person.archived_at is not None

        listed = await client.get("/api/v1/people")
        assert listed.json()["total"] == 0

        restored = await client.post(
            f"/api/v1/people/{person.id}/unarchive", headers=csrf_headers(token)
        )
        assert restored.status_code == 204
        await db_session.refresh(person)
        assert person.archived_at is None

    async def test_an_employee_cannot_archive(
        self, employee: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, token, actor = employee
        person = await create_person(db_session, created_by=actor.id)

        response = await client.post(
            f"/api/v1/people/{person.id}/archive", headers=csrf_headers(token)
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "FORBIDDEN"
        await db_session.refresh(person)
        assert person.archived_at is None

    async def test_archiving_twice_conflicts(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, token, actor = admin
        person = await create_person(db_session, created_by=actor.id, archived=True)

        response = await client.post(
            f"/api/v1/people/{person.id}/archive", headers=csrf_headers(token)
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "PERSON_ALREADY_ARCHIVED"


class TestUnauthenticated:
    async def test_the_directory_requires_a_session(self, db_client: AsyncClient) -> None:
        assert (await db_client.get("/api/v1/people")).status_code == 401

    async def test_create_requires_a_session(self, db_client: AsyncClient) -> None:
        response = await db_client.post("/api/v1/people", json=_create_body())
        assert response.status_code == 401
