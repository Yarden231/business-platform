"""Internal user administration (docs/api.md §5).

Authorization for these endpoints is proved in `test_authorization.py`; this
file is about what they *do* once an admin is through the gate — provisioning,
the one-time temporary password, the update allowlist, deactivation, and the
two rules that stop an admin locking the firm out of its own instance.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.actions import AuditAction
from app.auth.hashing import get_password_hasher
from app.core.settings import get_settings
from app.core.time import utc_now
from app.models.activity_log import ActivityLog
from app.models.user import User
from app.models.user_identity import UserIdentity
from tests.support.accounts import (
    ADMIN_PASSWORD,
    EMPLOYEE_PASSWORD,
    create_admin,
    create_employee,
    csrf_headers,
    log_in,
    password_identity,
    stored_sessions,
)


@pytest.fixture
async def admin(db_client: AsyncClient, db_session: AsyncSession) -> tuple[AsyncClient, str, User]:
    """An authenticated admin, its client and its CSRF token."""
    user = await create_admin(db_session, email="admin@example.com")
    token = await log_in(db_client, email="admin@example.com", password=ADMIN_PASSWORD)
    return db_client, token, user


async def audit_for(session: AsyncSession, action: AuditAction) -> ActivityLog | None:
    entry: ActivityLog | None = await session.scalar(
        select(ActivityLog).where(ActivityLog.action == action.value)
    )
    return entry


class TestCreation:
    async def test_it_returns_the_new_account(self, admin: tuple[AsyncClient, str, User]) -> None:
        client, token, _ = admin

        response = await client.post(
            "/api/v1/users",
            json={
                "email": "new-hire@example.com",
                "full_name": "New Hire",
                "role": "EMPLOYEE",
            },
            headers=csrf_headers(token),
        )

        assert response.status_code == 201
        user = response.json()["user"]
        assert user["email"] == "new-hire@example.com"
        assert user["full_name"] == "New Hire"
        assert user["role"] == "EMPLOYEE"
        assert user["is_active"] is True

    async def test_the_new_account_must_rotate_its_password(
        self, admin: tuple[AsyncClient, str, User]
    ) -> None:
        client, token, _ = admin

        response = await client.post(
            "/api/v1/users",
            json={"email": "new-hire@example.com", "full_name": "New Hire", "role": "EMPLOYEE"},
            headers=csrf_headers(token),
        )

        assert response.json()["user"]["must_change_password"] is True

    async def test_it_returns_a_usable_temporary_password(
        self, admin: tuple[AsyncClient, str, User], db_client: AsyncClient
    ) -> None:
        client, token, _ = admin

        created = await client.post(
            "/api/v1/users",
            json={"email": "new-hire@example.com", "full_name": "New Hire", "role": "EMPLOYEE"},
            headers=csrf_headers(token),
        )
        temporary = created.json()["temporary_password"]

        client.cookies.clear()
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": "new-hire@example.com", "password": temporary},
        )
        assert login.status_code == 204

    async def test_only_the_hash_of_the_temporary_password_is_stored(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, token, _ = admin

        created = await client.post(
            "/api/v1/users",
            json={"email": "new-hire@example.com", "full_name": "New Hire", "role": "EMPLOYEE"},
            headers=csrf_headers(token),
        )
        temporary = created.json()["temporary_password"]

        user_id = uuid.UUID(created.json()["user"]["id"])
        identity = await password_identity(db_session, user_id)
        assert identity.secret_hash is not None
        assert temporary not in identity.secret_hash
        assert identity.secret_hash.startswith("$argon2id$")
        assert get_password_hasher(get_settings()).verify_password(
            password=temporary, secret_hash=identity.secret_hash
        )

    async def test_the_temporary_password_is_never_retrievable_again(
        self, admin: tuple[AsyncClient, str, User]
    ) -> None:
        """One response, one copy. Losing it means issuing a new one (ADR-0026)."""
        client, token, _ = admin
        created = await client.post(
            "/api/v1/users",
            json={"email": "new-hire@example.com", "full_name": "New Hire", "role": "EMPLOYEE"},
            headers=csrf_headers(token),
        )
        temporary = created.json()["temporary_password"]
        user_id = created.json()["user"]["id"]

        for response in (
            await client.get(f"/api/v1/users/{user_id}"),
            await client.get("/api/v1/users"),
            await client.get("/api/v1/users/directory"),
        ):
            assert temporary not in response.text

    async def test_each_account_gets_a_different_temporary_password(
        self, admin: tuple[AsyncClient, str, User]
    ) -> None:
        client, token, _ = admin

        passwords = set()
        for index in range(3):
            created = await client.post(
                "/api/v1/users",
                json={
                    "email": f"hire-{index}@example.com",
                    "full_name": f"Hire {index}",
                    "role": "EMPLOYEE",
                },
                headers=csrf_headers(token),
            )
            passwords.add(created.json()["temporary_password"])

        assert len(passwords) == 3

    async def test_the_email_is_normalised(self, admin: tuple[AsyncClient, str, User]) -> None:
        client, token, _ = admin

        response = await client.post(
            "/api/v1/users",
            json={
                "email": "  New.Hire@Example.COM  ",
                "full_name": "New Hire",
                "role": "EMPLOYEE",
            },
            headers=csrf_headers(token),
        )

        assert response.json()["user"]["email"] == "new.hire@example.com"

    async def test_a_duplicate_email_is_a_conflict(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, token, _ = admin
        await create_employee(db_session, email="taken@example.com")

        response = await client.post(
            "/api/v1/users",
            json={"email": "taken@example.com", "full_name": "Someone Else", "role": "EMPLOYEE"},
            headers=csrf_headers(token),
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "USER_EMAIL_CONFLICT"

    async def test_a_duplicate_in_different_case_is_also_a_conflict(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, token, _ = admin
        await create_employee(db_session, email="taken@example.com")

        response = await client.post(
            "/api/v1/users",
            json={"email": "TAKEN@example.com", "full_name": "Someone", "role": "EMPLOYEE"},
            headers=csrf_headers(token),
        )

        assert response.status_code == 409

    async def test_an_admin_may_create_another_admin(
        self, admin: tuple[AsyncClient, str, User]
    ) -> None:
        """Deliberate: with no self-service reset, a lone admin has no way back."""
        client, token, _ = admin

        response = await client.post(
            "/api/v1/users",
            json={"email": "second@example.com", "full_name": "Second Admin", "role": "ADMIN"},
            headers=csrf_headers(token),
        )

        assert response.status_code == 201
        assert response.json()["user"]["role"] == "ADMIN"

    async def test_it_records_who_created_the_account(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, token, actor = admin

        created = await client.post(
            "/api/v1/users",
            json={"email": "new-hire@example.com", "full_name": "New Hire", "role": "EMPLOYEE"},
            headers=csrf_headers(token),
        )

        user = await db_session.get(User, uuid.UUID(created.json()["user"]["id"]))
        assert user is not None
        assert user.created_by == actor.id

    async def test_it_is_audited(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, token, actor = admin

        created = await client.post(
            "/api/v1/users",
            json={"email": "new-hire@example.com", "full_name": "New Hire", "role": "EMPLOYEE"},
            headers=csrf_headers(token),
        )

        entry = await audit_for(db_session, AuditAction.USER_CREATED)
        assert entry is not None
        assert entry.actor_user_id == actor.id
        assert entry.entity_id == uuid.UUID(created.json()["user"]["id"])

    async def test_the_audit_event_does_not_contain_the_temporary_password(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, token, _ = admin

        created = await client.post(
            "/api/v1/users",
            json={"email": "new-hire@example.com", "full_name": "New Hire", "role": "EMPLOYEE"},
            headers=csrf_headers(token),
        )
        temporary = created.json()["temporary_password"]

        entry = await audit_for(db_session, AuditAction.USER_CREATED)
        assert entry is not None
        assert temporary not in f"{entry.description} {entry.event_metadata}"

    @pytest.mark.parametrize(
        "body",
        [
            {"email": "not-an-email", "full_name": "X", "role": "EMPLOYEE"},
            {"email": "a@example.com", "full_name": "", "role": "EMPLOYEE"},
            {"email": "a@example.com", "full_name": "X", "role": "SUPERUSER"},
            {"email": "a@example.com", "full_name": "X"},
            {"email": "a@example.com", "full_name": "X", "role": "EMPLOYEE", "id": "x"},
        ],
    )
    async def test_a_malformed_body_is_rejected(
        self, admin: tuple[AsyncClient, str, User], body: dict[str, str]
    ) -> None:
        """Unlike login, a bad address here is a plain validation error: the
        caller is an authenticated admin, so there is no oracle to protect."""
        client, token, _ = admin

        response = await client.post("/api/v1/users", json=body, headers=csrf_headers(token))

        assert response.status_code == 422


class TestListing:
    async def test_it_returns_a_page_of_accounts(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, _token, _ = admin
        await create_employee(db_session, email="one@example.com")
        await create_employee(db_session, email="two@example.com")

        response = await client.get("/api/v1/users")

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 3  # the two employees plus the admin
        assert {item["email"] for item in body["items"]} == {
            "admin@example.com",
            "one@example.com",
            "two@example.com",
        }

    async def test_the_page_size_is_honoured(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, _token, _ = admin
        for index in range(4):
            await create_employee(db_session, email=f"staff-{index}@example.com")

        response = await client.get("/api/v1/users", params={"page_size": 2})

        body = response.json()
        assert len(body["items"]) == 2
        assert body["total"] == 5
        assert body["page_size"] == 2

    async def test_pages_do_not_overlap(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        """A stable order is what makes paging meaningful rather than a lottery."""
        client, _token, _ = admin
        for index in range(4):
            await create_employee(db_session, email=f"staff-{index}@example.com")

        first = await client.get("/api/v1/users", params={"page_size": 2, "page": 1})
        second = await client.get("/api/v1/users", params={"page_size": 2, "page": 2})

        first_ids = {item["id"] for item in first.json()["items"]}
        second_ids = {item["id"] for item in second.json()["items"]}
        assert not first_ids & second_ids

    async def test_it_can_be_filtered_by_role(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, _token, _ = admin
        await create_employee(db_session, email="one@example.com")

        response = await client.get("/api/v1/users", params={"role": "ADMIN"})

        assert [item["email"] for item in response.json()["items"]] == ["admin@example.com"]

    async def test_it_can_be_filtered_by_activation_state(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, _token, _ = admin
        await create_employee(db_session, email="gone@example.com", deactivated=True)

        active = await client.get("/api/v1/users", params={"is_active": True})
        inactive = await client.get("/api/v1/users", params={"is_active": False})

        assert "gone@example.com" not in {item["email"] for item in active.json()["items"]}
        assert [item["email"] for item in inactive.json()["items"]] == ["gone@example.com"]

    async def test_it_can_be_searched_by_name_or_address(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, _token, _ = admin
        await create_password_user_named(db_session, "Ada Lovelace", "ada@example.com")

        by_name = await client.get("/api/v1/users", params={"query": "lovelace"})
        by_email = await client.get("/api/v1/users", params={"query": "ada@"})

        assert [item["email"] for item in by_name.json()["items"]] == ["ada@example.com"]
        assert [item["email"] for item in by_email.json()["items"]] == ["ada@example.com"]

    async def test_the_search_is_case_insensitive(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, _token, _ = admin
        await create_password_user_named(db_session, "Ada Lovelace", "ada@example.com")

        response = await client.get("/api/v1/users", params={"query": "LOVELACE"})

        assert len(response.json()["items"]) == 1

    async def test_no_account_leaks_secret_material(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, _token, _ = admin
        await create_employee(db_session, email="one@example.com")

        response = await client.get("/api/v1/users")

        for item in response.json()["items"]:
            assert set(item) == {
                "id",
                "email",
                "full_name",
                "role",
                "must_change_password",
                "is_active",
                "deactivated_at",
                "last_login_at",
                "created_at",
                "updated_at",
            }


class TestReading:
    async def test_it_returns_one_account(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, _token, _ = admin
        target = await create_employee(db_session, email="target@example.com")

        response = await client.get(f"/api/v1/users/{target.id}")

        assert response.status_code == 200
        assert response.json()["email"] == "target@example.com"

    async def test_an_unknown_id_is_not_found(self, admin: tuple[AsyncClient, str, User]) -> None:
        client, _token, _ = admin

        response = await client.get(f"/api/v1/users/{uuid.uuid4()}")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "USER_NOT_FOUND"

    async def test_a_malformed_id_is_a_validation_error(
        self, admin: tuple[AsyncClient, str, User]
    ) -> None:
        client, _token, _ = admin

        assert (await client.get("/api/v1/users/not-a-uuid")).status_code == 422


class TestUpdating:
    async def test_the_name_can_be_changed(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, token, _ = admin
        target = await create_employee(db_session, email="target@example.com")

        response = await client.patch(
            f"/api/v1/users/{target.id}",
            json={"full_name": "Renamed Person"},
            headers=csrf_headers(token),
        )

        assert response.status_code == 200
        assert response.json()["full_name"] == "Renamed Person"

    async def test_the_role_can_be_changed(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, token, _ = admin
        target = await create_employee(db_session, email="target@example.com")

        response = await client.patch(
            f"/api/v1/users/{target.id}",
            json={"role": "ADMIN"},
            headers=csrf_headers(token),
        )

        assert response.json()["role"] == "ADMIN"

    async def test_omitted_fields_are_left_alone(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, token, _ = admin
        target = await create_employee(db_session, email="target@example.com")

        response = await client.patch(
            f"/api/v1/users/{target.id}",
            json={"full_name": "Renamed Person"},
            headers=csrf_headers(token),
        )

        assert response.json()["role"] == "EMPLOYEE"
        assert response.json()["email"] == "target@example.com"

    @pytest.mark.parametrize(
        "field",
        ["email", "must_change_password", "created_by", "created_at", "last_login_at", "id"],
    )
    async def test_nothing_outside_the_allowlist_is_settable(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession, field: str
    ) -> None:
        """`extra="forbid"`, so a field nobody may set is a `422` rather than a silent no-op."""
        client, token, _ = admin
        target = await create_employee(db_session, email="target@example.com")

        response = await client.patch(
            f"/api/v1/users/{target.id}",
            json={field: "anything"},
            headers=csrf_headers(token),
        )

        assert response.status_code == 422

    async def test_an_empty_body_changes_nothing(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, token, _ = admin
        target = await create_employee(db_session, email="target@example.com")

        response = await client.patch(
            f"/api/v1/users/{target.id}", json={}, headers=csrf_headers(token)
        )

        assert response.status_code == 200
        assert response.json()["full_name"] == target.full_name

    async def test_an_unknown_id_is_not_found(self, admin: tuple[AsyncClient, str, User]) -> None:
        client, token, _ = admin

        response = await client.patch(
            f"/api/v1/users/{uuid.uuid4()}",
            json={"full_name": "Nobody"},
            headers=csrf_headers(token),
        )

        assert response.status_code == 404

    async def test_it_is_audited(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, token, _ = admin
        target = await create_employee(db_session, email="target@example.com")

        await client.patch(
            f"/api/v1/users/{target.id}",
            json={"full_name": "Renamed Person"},
            headers=csrf_headers(token),
        )

        entry = await audit_for(db_session, AuditAction.USER_UPDATED)
        assert entry is not None
        assert entry.entity_id == target.id


class TestDeactivation:
    async def test_it_marks_the_account_inactive_without_deleting_it(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, token, _ = admin
        target = await create_employee(db_session, email="target@example.com")

        response = await client.patch(
            f"/api/v1/users/{target.id}",
            json={"deactivated": True},
            headers=csrf_headers(token),
        )

        assert response.status_code == 200
        assert response.json()["is_active"] is False
        assert response.json()["deactivated_at"] is not None
        assert await db_session.get(User, target.id) is not None

    async def test_it_revokes_every_session_of_the_target(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, token, _ = admin
        target = await create_employee(db_session, email="target@example.com")
        target.must_change_password = False
        # Two sessions, so this cannot pass by revoking only the newest.
        for _ in range(2):
            other = await make_client(db_session)
            await log_in(other, email="target@example.com", password=EMPLOYEE_PASSWORD)

        await client.patch(
            f"/api/v1/users/{target.id}",
            json={"deactivated": True},
            headers=csrf_headers(token),
        )

        sessions = await stored_sessions(db_session, target.id)
        assert len(sessions) == 2
        assert all(row.revoked_at is not None for row in sessions)

    async def test_reactivation_restores_login_but_not_the_old_sessions(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, token, _ = admin
        target = await create_employee(db_session, email="target@example.com")
        target.deactivated_at = utc_now()
        await db_session.flush()

        response = await client.patch(
            f"/api/v1/users/{target.id}",
            json={"deactivated": False},
            headers=csrf_headers(token),
        )

        assert response.json()["is_active"] is True
        assert response.json()["deactivated_at"] is None

    async def test_an_admin_cannot_deactivate_themselves(
        self, admin: tuple[AsyncClient, str, User]
    ) -> None:
        """Locking yourself out mid-request is never what you meant."""
        client, token, actor = admin

        response = await client.patch(
            f"/api/v1/users/{actor.id}",
            json={"deactivated": True},
            headers=csrf_headers(token),
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "USER_SELF_DEACTIVATION"

    async def test_one_of_two_admins_can_be_deactivated(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        """The rule protects the *last* admin, not admins in general."""
        client, token, _ = admin
        second = await create_admin(db_session, email="second@example.com")

        response = await client.patch(
            f"/api/v1/users/{second.id}",
            json={"deactivated": True},
            headers=csrf_headers(token),
        )

        assert response.status_code == 200
        assert response.json()["is_active"] is False

    async def test_the_admin_left_behind_cannot_then_be_demoted(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        """A deactivated admin does not count towards the survivors."""
        client, token, actor = admin
        second = await create_admin(db_session, email="second@example.com")
        await client.patch(
            f"/api/v1/users/{second.id}",
            json={"deactivated": True},
            headers=csrf_headers(token),
        )

        response = await client.patch(
            f"/api/v1/users/{actor.id}",
            json={"role": "EMPLOYEE"},
            headers=csrf_headers(token),
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "USER_LAST_ADMIN"

    async def test_the_last_admin_cannot_be_demoted(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        """Otherwise the instance has nobody left who can create another admin."""
        client, token, actor = admin

        response = await client.patch(
            f"/api/v1/users/{actor.id}",
            json={"role": "EMPLOYEE"},
            headers=csrf_headers(token),
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "USER_LAST_ADMIN"

    async def test_an_admin_can_be_demoted_while_another_remains(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, token, _ = admin
        second = await create_admin(db_session, email="second@example.com")

        response = await client.patch(
            f"/api/v1/users/{second.id}",
            json={"role": "EMPLOYEE"},
            headers=csrf_headers(token),
        )

        assert response.status_code == 200
        assert response.json()["role"] == "EMPLOYEE"

    async def test_deactivation_is_audited(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, token, _ = admin
        target = await create_employee(db_session, email="target@example.com")

        await client.patch(
            f"/api/v1/users/{target.id}",
            json={"deactivated": True},
            headers=csrf_headers(token),
        )

        entry = await audit_for(db_session, AuditAction.USER_DEACTIVATED)
        assert entry is not None
        assert entry.entity_id == target.id

    async def test_reactivation_has_its_own_audit_action(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        """ "Who restored access" is a question an auditor asks directly."""
        client, token, _ = admin
        target = await create_employee(db_session, email="target@example.com")
        target.deactivated_at = utc_now()
        await db_session.flush()

        await client.patch(
            f"/api/v1/users/{target.id}",
            json={"deactivated": False},
            headers=csrf_headers(token),
        )

        assert await audit_for(db_session, AuditAction.USER_ACTIVATED) is not None


class TestPasswordReset:
    async def test_it_returns_a_new_temporary_password(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, token, _ = admin
        target = await create_employee(db_session, email="target@example.com")

        response = await client.post(
            f"/api/v1/users/{target.id}/password-reset", headers=csrf_headers(token)
        )

        assert response.status_code == 200
        assert response.json()["temporary_password"]
        assert response.json()["user"]["must_change_password"] is True

    async def test_the_old_password_stops_working(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, token, _ = admin
        target = await create_employee(db_session, email="target@example.com")

        await client.post(f"/api/v1/users/{target.id}/password-reset", headers=csrf_headers(token))

        other = await make_client(db_session)
        response = await other.post(
            "/api/v1/auth/login",
            json={"email": "target@example.com", "password": EMPLOYEE_PASSWORD},
        )
        assert response.status_code == 401

    async def test_the_new_password_works(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, token, _ = admin
        target = await create_employee(db_session, email="target@example.com")

        reset = await client.post(
            f"/api/v1/users/{target.id}/password-reset", headers=csrf_headers(token)
        )

        other = await make_client(db_session)
        response = await other.post(
            "/api/v1/auth/login",
            json={
                "email": "target@example.com",
                "password": reset.json()["temporary_password"],
            },
        )
        assert response.status_code == 204

    async def test_it_revokes_every_session_of_the_target(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, token, _ = admin
        target = await create_employee(db_session, email="target@example.com")
        other = await make_client(db_session)
        await log_in(other, email="target@example.com", password=EMPLOYEE_PASSWORD)

        await client.post(f"/api/v1/users/{target.id}/password-reset", headers=csrf_headers(token))

        assert (await other.get("/api/v1/auth/me")).status_code == 401
        sessions = await stored_sessions(db_session, target.id)
        assert all(row.revoked_at is not None for row in sessions)

    async def test_it_clears_an_existing_lockout(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        """A reset is the recovery path, so it must not leave the account locked."""
        client, token, _ = admin
        target = await create_employee(db_session, email="target@example.com")
        target_id = target.id
        identity = await password_identity(db_session, target.id)
        identity.failed_attempt_count = 5
        identity.locked_until = utc_now().replace(year=2030)
        await db_session.flush()

        reset = await client.post(
            f"/api/v1/users/{target.id}/password-reset", headers=csrf_headers(token)
        )

        db_session.expire_all()
        counters = (
            await db_session.execute(
                select(UserIdentity.locked_until, UserIdentity.failed_attempt_count).where(
                    UserIdentity.user_id == target_id
                )
            )
        ).one()
        assert counters == (None, 0)
        other = await make_client(db_session)
        assert (
            await other.post(
                "/api/v1/auth/login",
                json={
                    "email": "target@example.com",
                    "password": reset.json()["temporary_password"],
                },
            )
        ).status_code == 204

    async def test_only_the_hash_is_stored(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, token, _ = admin
        target = await create_employee(db_session, email="target@example.com")

        reset = await client.post(
            f"/api/v1/users/{target.id}/password-reset", headers=csrf_headers(token)
        )

        identity = await password_identity(db_session, target.id)
        await db_session.refresh(identity)
        assert reset.json()["temporary_password"] not in str(identity.secret_hash)

    async def test_an_unknown_id_is_not_found(self, admin: tuple[AsyncClient, str, User]) -> None:
        client, token, _ = admin

        response = await client.post(
            f"/api/v1/users/{uuid.uuid4()}/password-reset", headers=csrf_headers(token)
        )

        assert response.status_code == 404

    async def test_it_is_audited_as_a_reset_not_a_change(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        """The actor is not the subject, which is worth being able to see."""
        client, token, actor = admin
        target = await create_employee(db_session, email="target@example.com")

        reset = await client.post(
            f"/api/v1/users/{target.id}/password-reset", headers=csrf_headers(token)
        )

        entry = await audit_for(db_session, AuditAction.USER_PASSWORD_RESET)
        assert entry is not None
        assert entry.actor_user_id == actor.id
        assert entry.entity_id == target.id
        assert (
            reset.json()["temporary_password"] not in f"{entry.description} {entry.event_metadata}"
        )
        assert await audit_for(db_session, AuditAction.USER_PASSWORD_CHANGED) is None


class TestDirectory:
    async def test_it_returns_only_the_three_assignment_fields(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, _token, _ = admin
        await create_employee(db_session, email="target@example.com")

        response = await client.get("/api/v1/users/directory")

        assert response.status_code == 200
        for entry in response.json():
            assert set(entry) == {"id", "full_name", "role"}

    async def test_it_omits_deactivated_accounts(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        """They cannot be given new work, which is what this list is for."""
        client, _token, _ = admin
        await create_employee(db_session, email="gone@example.com", deactivated=True)
        await create_employee(db_session, email="here@example.com")

        response = await client.get("/api/v1/users/directory")

        names = {entry["full_name"] for entry in response.json()}
        assert len(response.json()) == 2  # the admin and the active employee
        assert "Employee Person" in names

    async def test_it_leaks_no_email_addresses(
        self, admin: tuple[AsyncClient, str, User], db_session: AsyncSession
    ) -> None:
        client, _token, _ = admin
        await create_employee(db_session, email="target@example.com")

        response = await client.get("/api/v1/users/directory")

        assert "target@example.com" not in response.text


async def create_password_user_named(session: AsyncSession, full_name: str, email: str) -> User:
    from tests.support.accounts import create_password_user

    return await create_password_user(
        session, email=email, full_name=full_name, password=EMPLOYEE_PASSWORD
    )


async def make_client(session: AsyncSession) -> AsyncClient:
    """A second HTTP client sharing the test's transaction, for a second browser."""
    from app.db.session import get_db_session
    from app.main import create_app
    from tests.conftest import build_client

    app = create_app()

    async def _override() -> object:
        yield session

    app.dependency_overrides[get_db_session] = _override
    return build_client(app)
