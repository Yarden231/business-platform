"""The six end-to-end flows of the Phase 2 specification.

Every one of these is covered in pieces by the other files in this directory.
They are written out again here as whole journeys because the pieces passing
individually does not prove the sequence works: a flow is where ordering bugs
live — a session revoked before the replacement is issued, a gate that lifts
one request too late, a temporary password that works only because the previous
one was never actually invalidated.

Each test reads as the numbered flow it implements, in order, with the
assertions in line.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cookies import SESSION_COOKIE_NAME
from app.core.settings import get_settings
from app.repositories.users import UserRepository
from app.services.admin_bootstrap import AdminBootstrapService, BootstrapOutcome
from tests.integration.test_user_management import make_client
from tests.support.accounts import (
    ADMIN_PASSWORD,
    csrf_headers,
    log_in,
    password_identity,
    stored_sessions,
)

BOOTSTRAP_EMAIL = "founder@example.com"
BOOTSTRAP_PASSWORD = "bootstrap development passphrase"
CHOSEN_PASSWORD = "a chosen personal passphrase"


class TestFlowAAdminBootstrap:
    async def test_a_bootstrapped_admin_can_log_in_and_read_its_identity(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        # 1. Create the first admin through the service the CLI drives.
        result = await AdminBootstrapService(db_session, get_settings()).create_initial_admin(
            email=f"  {BOOTSTRAP_EMAIL.upper()}  ",
            full_name="Founding Admin",
            password=BOOTSTRAP_PASSWORD,
        )
        assert result.outcome is BootstrapOutcome.CREATED
        assert result.email == BOOTSTRAP_EMAIL  # normalised on the way in

        created = await UserRepository(db_session).get_by_email(BOOTSTRAP_EMAIL)
        assert created is not None
        assert created.created_by is None  # nobody created it, and the row says so

        # 2. The password exists only as an Argon2id hash.
        identity = await password_identity(db_session, created.id)
        assert identity.secret_hash is not None
        assert identity.secret_hash.startswith("$argon2id$")
        assert BOOTSTRAP_PASSWORD not in identity.secret_hash

        # 3. The admin can log in with it.
        login = await db_client.post(
            "/api/v1/auth/login",
            json={"email": BOOTSTRAP_EMAIL, "password": BOOTSTRAP_PASSWORD},
        )
        assert login.status_code == 204

        # 4. `/auth/me` returns the safe identity, and nothing else.
        me = await db_client.get("/api/v1/auth/me")
        assert me.status_code == 200
        assert me.json() == {
            "id": str(created.id),
            "email": BOOTSTRAP_EMAIL,
            "full_name": "Founding Admin",
            "role": "ADMIN",
            "must_change_password": False,
        }

        # 5. Being a chosen password rather than an issued one, no rotation is forced.
        assert (await db_client.get("/api/v1/users")).status_code == 200


class TestFlowBEmployeeProvisioning:
    async def test_a_provisioned_employee_rotates_its_password_and_gets_to_work(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        from tests.support.accounts import create_admin

        # 1. An authenticated admin.
        await create_admin(db_session, email="admin@example.com")
        admin_token = await log_in(db_client, email="admin@example.com", password=ADMIN_PASSWORD)

        # 2. Creates an employee, and is handed the temporary password once.
        created = await db_client.post(
            "/api/v1/users",
            json={"email": "hire@example.com", "full_name": "New Hire", "role": "EMPLOYEE"},
            headers=csrf_headers(admin_token),
        )
        assert created.status_code == 201
        temporary = created.json()["temporary_password"]
        employee_id = uuid.UUID(created.json()["user"]["id"])

        # 3. The database holds only its hash.
        identity = await password_identity(db_session, employee_id)
        assert identity.secret_hash is not None
        assert temporary not in identity.secret_hash

        # 4. The employee logs in with it, on their own browser.
        employee = await make_client(db_session)
        employee_token = await log_in(employee, email="hire@example.com", password=temporary)

        # 5. An ordinary endpoint is blocked until the password is rotated.
        blocked = await employee.get("/api/v1/users/directory")
        assert blocked.status_code == 403
        assert blocked.json()["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"

        # 6. They change it.
        changed = await employee.post(
            "/api/v1/auth/password",
            json={"current_password": temporary, "new_password": CHOSEN_PASSWORD},
            headers=csrf_headers(employee_token),
        )
        assert changed.status_code == 204

        # 7. A fresh session was issued in place of the old one.
        assert employee.cookies[SESSION_COOKIE_NAME]
        me = await employee.get("/api/v1/auth/me")
        assert me.status_code == 200
        assert me.json()["must_change_password"] is False

        # 8. And the ordinary endpoint now works.
        assert (await employee.get("/api/v1/users/directory")).status_code == 200

        # 9. The temporary password is spent.
        spent = await make_client(db_session)
        assert (
            await spent.post(
                "/api/v1/auth/login",
                json={"email": "hire@example.com", "password": temporary},
            )
        ).status_code == 401


class TestFlowCLogout:
    async def test_logging_out_makes_the_old_cookie_useless(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        from tests.support.accounts import EMPLOYEE_PASSWORD, create_employee

        # 1. A logged-in employee with a working session.
        user = await create_employee(db_session)
        token = await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)
        assert (await db_client.get("/api/v1/auth/me")).status_code == 200
        cookie = db_client.cookies[SESSION_COOKIE_NAME]

        # 2. Logout, with the CSRF token.
        logout = await db_client.post("/api/v1/auth/logout", headers=csrf_headers(token))
        assert logout.status_code == 204

        # 3. The row is revoked server-side, not merely forgotten by the browser.
        sessions = await stored_sessions(db_session, user.id)
        assert len(sessions) == 1
        assert sessions[0].revoked_at is not None

        # 4. And the old cookie no longer authenticates, even if the browser kept it.
        db_client.cookies.set(SESSION_COOKIE_NAME, cookie)
        assert (await db_client.get("/api/v1/auth/me")).status_code == 401


class TestFlowDAdminReset:
    async def test_an_admin_reset_locks_the_employee_out_of_everything_old(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        from tests.support.accounts import EMPLOYEE_PASSWORD, create_admin, create_employee

        # 1. An employee with a live session, and an admin.
        employee_user = await create_employee(db_session, email="employee@example.com")
        employee = await make_client(db_session)
        await log_in(employee, email="employee@example.com", password=EMPLOYEE_PASSWORD)
        assert (await employee.get("/api/v1/auth/me")).status_code == 200

        await create_admin(db_session, email="admin@example.com")
        admin_token = await log_in(db_client, email="admin@example.com", password=ADMIN_PASSWORD)

        # 2. The admin resets the employee's password.
        reset = await db_client.post(
            f"/api/v1/users/{employee_user.id}/password-reset",
            headers=csrf_headers(admin_token),
        )
        assert reset.status_code == 200
        temporary = reset.json()["temporary_password"]

        # 3. Every session the employee had is revoked immediately.
        assert (await employee.get("/api/v1/auth/me")).status_code == 401
        sessions = await stored_sessions(db_session, employee_user.id)
        assert all(row.revoked_at is not None for row in sessions)

        # 4. The old password no longer works.
        fresh = await make_client(db_session)
        assert (
            await fresh.post(
                "/api/v1/auth/login",
                json={"email": "employee@example.com", "password": EMPLOYEE_PASSWORD},
            )
        ).status_code == 401

        # 5. The new temporary password does.
        assert (
            await fresh.post(
                "/api/v1/auth/login",
                json={"email": "employee@example.com", "password": temporary},
            )
        ).status_code == 204

        # 6. And it lands the employee back in the forced-rotation state.
        me = await fresh.get("/api/v1/auth/me")
        assert me.json()["must_change_password"] is True
        assert (await fresh.get("/api/v1/users/directory")).status_code == 403


class TestFlowEDeactivation:
    async def test_deactivation_ends_the_session_and_bars_new_ones(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        from tests.support.accounts import EMPLOYEE_PASSWORD, create_admin, create_employee

        # 1. An employee with an active session.
        employee_user = await create_employee(db_session, email="employee@example.com")
        employee = await make_client(db_session)
        await log_in(employee, email="employee@example.com", password=EMPLOYEE_PASSWORD)
        assert (await employee.get("/api/v1/auth/me")).status_code == 200

        await create_admin(db_session, email="admin@example.com")
        admin_token = await log_in(db_client, email="admin@example.com", password=ADMIN_PASSWORD)

        # 2. The admin deactivates them.
        deactivated = await db_client.patch(
            f"/api/v1/users/{employee_user.id}",
            json={"deactivated": True},
            headers=csrf_headers(admin_token),
        )
        assert deactivated.status_code == 200
        assert deactivated.json()["is_active"] is False

        # 3. Their session is revoked, so the very next request fails.
        assert (await employee.get("/api/v1/auth/me")).status_code == 401
        sessions = await stored_sessions(db_session, employee_user.id)
        assert all(row.revoked_at is not None for row in sessions)

        # 4. And they cannot log in again, with the right password or otherwise.
        fresh = await make_client(db_session)
        refused = await fresh.post(
            "/api/v1/auth/login",
            json={"email": "employee@example.com", "password": EMPLOYEE_PASSWORD},
        )
        assert refused.status_code == 401
        assert refused.json()["error"]["code"] == "AUTH_INVALID_CREDENTIALS"

        # 5. The account still exists, so historical audit rows still resolve.
        assert (await db_client.get(f"/api/v1/users/{employee_user.id}")).status_code == 200


class TestFlowFCsrfIsSessionBound:
    async def test_a_token_from_one_session_cannot_act_on_another(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        from tests.support.accounts import EMPLOYEE_PASSWORD, create_employee

        await create_employee(db_session, email="employee@example.com")

        # 1. Session A, and its CSRF token.
        client_a = await make_client(db_session)
        token_a = await log_in(client_a, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        # 2. Session B, for the same user, with its own token.
        client_b = await make_client(db_session)
        token_b = await log_in(client_b, email="employee@example.com", password=EMPLOYEE_PASSWORD)
        assert token_a != token_b

        # 3. Token A presented with session B is refused.
        crossed = await client_b.post("/api/v1/auth/logout", headers=csrf_headers(token_a))
        assert crossed.status_code == 403
        assert crossed.json()["error"]["code"] == "CSRF_TOKEN_INVALID"

        # 4. Each token still works with the session it belongs to, so the
        #    refusal above was the binding and not a blanket failure.
        assert (
            await client_b.post("/api/v1/auth/logout", headers=csrf_headers(token_b))
        ).status_code == 204
        assert (
            await client_a.post("/api/v1/auth/logout", headers=csrf_headers(token_a))
        ).status_code == 204
