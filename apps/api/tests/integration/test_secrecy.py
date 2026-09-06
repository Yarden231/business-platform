"""Where secrets are allowed to exist, and where they are not (docs/security.md §5).

The other files each prove that one endpoint behaves. These sweep instead: every
table, every response, every log line. A leak introduced by a future endpoint is
much more likely to be caught by a test that looks everywhere than by one that
looks at the endpoint whose author already thought about it.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cookies import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
from app.db.base import Base
from tests.support.accounts import (
    ADMIN_PASSWORD,
    create_admin,
    csrf_headers,
    log_in,
    password_identity,
    stored_sessions,
)
from tests.support.logs import LogReader, capture_json_logs, rendered

#: Distinctive enough that finding it anywhere is unambiguous.
SECRET = "Tr0ubador-Distinctive-Secret-42"


async def every_text_value(session: AsyncSession) -> str:
    """Every value of every column of every table, as one searchable string.

    Deliberately brute force. A per-column assertion would have to be updated
    whenever a table is added, which is exactly when it would be forgotten.
    """
    chunks: list[str] = []
    for table in Base.metadata.sorted_tables:
        rows = await session.execute(select(table))
        for row in rows:
            chunks.append(" ".join(repr(value) for value in row))
    return "\n".join(chunks)


class TestPasswordsAreNeverPersisted:
    async def test_a_login_leaves_no_trace_of_the_password(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await create_admin(db_session, email="admin@example.com")

        await db_client.post(
            "/api/v1/auth/login", json={"email": "admin@example.com", "password": SECRET}
        )

        assert SECRET not in await every_text_value(db_session)

    async def test_a_successful_login_leaves_no_trace_either(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        from tests.support.accounts import create_password_user

        await create_password_user(db_session, email="user@example.com", password=SECRET)

        await db_client.post(
            "/api/v1/auth/login", json={"email": "user@example.com", "password": SECRET}
        )

        assert SECRET not in await every_text_value(db_session)

    async def test_a_password_change_leaves_no_trace(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await create_admin(db_session, email="admin@example.com")
        token = await log_in(db_client, email="admin@example.com", password=ADMIN_PASSWORD)

        await db_client.post(
            "/api/v1/auth/password",
            json={"current_password": ADMIN_PASSWORD, "new_password": SECRET},
            headers=csrf_headers(token),
        )

        assert SECRET not in await every_text_value(db_session)

    async def test_provisioning_leaves_no_trace_of_the_temporary_password(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await create_admin(db_session, email="admin@example.com")
        token = await log_in(db_client, email="admin@example.com", password=ADMIN_PASSWORD)

        created = await db_client.post(
            "/api/v1/users",
            json={"email": "hire@example.com", "full_name": "New Hire", "role": "EMPLOYEE"},
            headers=csrf_headers(token),
        )

        temporary = created.json()["temporary_password"]
        assert temporary not in await every_text_value(db_session)

    async def test_a_rejected_password_leaves_no_trace(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A validation failure is the easiest place to accidentally echo an input."""
        await create_admin(db_session, email="admin@example.com")
        token = await log_in(db_client, email="admin@example.com", password=ADMIN_PASSWORD)

        await db_client.post(
            "/api/v1/auth/password",
            json={"current_password": "wrong", "new_password": SECRET},
            headers=csrf_headers(token),
        )

        assert SECRET not in await every_text_value(db_session)


class TestTokensAreOnlyStoredHashed:
    async def test_the_raw_session_token_is_nowhere_in_the_database(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await create_admin(db_session, email="admin@example.com")
        await log_in(db_client, email="admin@example.com", password=ADMIN_PASSWORD)

        raw = db_client.cookies[SESSION_COOKIE_NAME]

        assert raw not in await every_text_value(db_session)

    async def test_the_raw_csrf_token_is_nowhere_in_the_database(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await create_admin(db_session, email="admin@example.com")
        await log_in(db_client, email="admin@example.com", password=ADMIN_PASSWORD)

        raw = db_client.cookies[CSRF_COOKIE_NAME]

        assert raw not in await every_text_value(db_session)

    async def test_the_hashes_are_there_instead(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The negative tests above would also pass if nothing were stored at all."""
        from app.auth.tokens import hash_token

        user = await create_admin(db_session, email="admin@example.com")
        await log_in(db_client, email="admin@example.com", password=ADMIN_PASSWORD)

        stored = (await stored_sessions(db_session, user.id))[0]
        assert stored.token_hash == hash_token(db_client.cookies[SESSION_COOKIE_NAME])
        assert stored.csrf_token_hash == hash_token(db_client.cookies[CSRF_COOKIE_NAME])


class TestHashesAreNeverReturned:
    async def test_no_endpoint_returns_the_password_hash(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin = await create_admin(db_session, email="admin@example.com")
        token = await log_in(db_client, email="admin@example.com", password=ADMIN_PASSWORD)
        secret_hash = (await password_identity(db_session, admin.id)).secret_hash
        assert secret_hash is not None

        responses = [
            await db_client.get("/api/v1/auth/me"),
            await db_client.get("/api/v1/users"),
            await db_client.get(f"/api/v1/users/{admin.id}"),
            await db_client.get("/api/v1/users/directory"),
            await db_client.post(
                "/api/v1/users",
                json={"email": "hire@example.com", "full_name": "H", "role": "EMPLOYEE"},
                headers=csrf_headers(token),
            ),
        ]

        for response in responses:
            assert secret_hash not in response.text
            assert "argon2" not in response.text.lower()

    async def test_no_endpoint_returns_session_or_csrf_hashes(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin = await create_admin(db_session, email="admin@example.com")
        await log_in(db_client, email="admin@example.com", password=ADMIN_PASSWORD)
        stored = (await stored_sessions(db_session, admin.id))[0]

        for response in (
            await db_client.get("/api/v1/auth/me"),
            await db_client.get("/api/v1/users"),
            await db_client.get(f"/api/v1/users/{admin.id}"),
        ):
            assert stored.token_hash not in response.text
            assert stored.csrf_token_hash not in response.text

    @pytest.mark.parametrize(
        "forbidden",
        [
            "secret_hash",
            "token_hash",
            "csrf_token_hash",
            "failed_attempt_count",
            "locked_until",
            "created_by",
        ],
    )
    async def test_no_internal_field_name_appears_in_a_response(
        self, db_client: AsyncClient, db_session: AsyncSession, forbidden: str
    ) -> None:
        """Field names are a map of the schema; these are nobody's business."""
        admin = await create_admin(db_session, email="admin@example.com")
        await log_in(db_client, email="admin@example.com", password=ADMIN_PASSWORD)

        for response in (
            await db_client.get("/api/v1/auth/me"),
            await db_client.get("/api/v1/users"),
            await db_client.get(f"/api/v1/users/{admin.id}"),
            await db_client.get("/api/v1/users/directory"),
        ):
            assert forbidden not in response.text


class TestTheOpenApiDocumentAgrees:
    """The published contract must not describe fields the API refuses to return."""

    @pytest.mark.parametrize(
        "forbidden",
        ["secret_hash", "token_hash", "csrf_token_hash", "failed_attempt_count", "locked_until"],
    )
    async def test_no_schema_declares_a_secret_field(
        self, db_client: AsyncClient, forbidden: str
    ) -> None:
        """Property names, not the whole document: a schema *description* may
        legitimately explain which columns are deliberately absent, and several do."""
        document = (await db_client.get("/openapi.json")).json()

        declared = {
            name
            for schema in document["components"]["schemas"].values()
            for name in schema.get("properties", {})
        }
        assert forbidden not in declared

    async def test_the_new_endpoints_are_documented(self, db_client: AsyncClient) -> None:
        document = (await db_client.get("/openapi.json")).json()

        assert {
            "/api/v1/auth/login",
            "/api/v1/auth/logout",
            "/api/v1/auth/me",
            "/api/v1/auth/password",
            "/api/v1/users",
            "/api/v1/users/{user_id}",
            "/api/v1/users/{user_id}/password-reset",
            "/api/v1/users/directory",
        } <= set(document["paths"])

    async def test_the_login_body_is_a_typed_schema(self, db_client: AsyncClient) -> None:
        document = (await db_client.get("/openapi.json")).json()

        body = document["paths"]["/api/v1/auth/login"]["post"]["requestBody"]
        assert body["content"]["application/json"]["schema"]["$ref"].endswith("LoginRequest")

    async def test_the_temporary_password_is_documented_as_shown_once(
        self, db_client: AsyncClient
    ) -> None:
        document = (await db_client.get("/openapi.json")).json()

        field = document["components"]["schemas"]["ProvisionedUserResponse"]["properties"][
            "temporary_password"
        ]
        assert "once" in field["description"].lower()


class TestLoggingPrivacy:
    """docs/security.md §5: the request log is not a place credentials may appear.

    The log is read back through the real pipeline (`tests/support/logs.py`)
    rather than with `capsys` or `capfd`, neither of which sees these lines —
    an assertion against an empty string would pass whatever leaked, which for
    this class would be worse than having no tests. The first case below exists
    to keep the rest honest.
    """

    @pytest.fixture
    def logs(self, monkeypatch: pytest.MonkeyPatch) -> LogReader:
        return capture_json_logs(monkeypatch)

    async def test_the_log_is_really_being_read(
        self, db_client: AsyncClient, db_session: AsyncSession, logs: LogReader
    ) -> None:
        user = await create_admin(db_session, email="admin@example.com")
        await log_in(db_client, email="admin@example.com", password=ADMIN_PASSWORD)

        await db_client.get("/api/v1/auth/me")

        entries = [entry for entry in logs() if entry.get("event") == "http_request"]
        assert entries, "no request was logged, so the assertions below prove nothing"
        # The safe metadata an investigator needs in order to correlate.
        assert entries[-1]["request_id"]
        assert entries[-1]["user_id"] == str(user.id)

    async def test_a_failed_login_logs_no_credential_material(
        self, db_client: AsyncClient, db_session: AsyncSession, logs: LogReader
    ) -> None:
        await create_admin(db_session, email="admin@example.com")

        await db_client.post(
            "/api/v1/auth/login", json={"email": "admin@example.com", "password": SECRET}
        )

        assert SECRET not in rendered(logs)

    async def test_a_successful_login_logs_neither_token(
        self, db_client: AsyncClient, db_session: AsyncSession, logs: LogReader
    ) -> None:
        await create_admin(db_session, email="admin@example.com")

        await log_in(db_client, email="admin@example.com", password=ADMIN_PASSWORD)

        logged = rendered(logs)
        assert db_client.cookies[SESSION_COOKIE_NAME] not in logged
        assert db_client.cookies[CSRF_COOKIE_NAME] not in logged

    async def test_no_request_or_response_header_is_logged(
        self, db_client: AsyncClient, db_session: AsyncSession, logs: LogReader
    ) -> None:
        """No `Cookie`, no `Set-Cookie`, and no room for an `Authorization` header later."""
        await create_admin(db_session, email="admin@example.com")
        await log_in(db_client, email="admin@example.com", password=ADMIN_PASSWORD)

        await db_client.get("/api/v1/auth/me")

        logged = rendered(logs).lower()
        assert "cookie" not in logged
        assert "authorization" not in logged

    async def test_a_password_change_logs_neither_password(
        self, db_client: AsyncClient, db_session: AsyncSession, logs: LogReader
    ) -> None:
        await create_admin(db_session, email="admin@example.com")
        token = await log_in(db_client, email="admin@example.com", password=ADMIN_PASSWORD)

        await db_client.post(
            "/api/v1/auth/password",
            json={"current_password": ADMIN_PASSWORD, "new_password": SECRET},
            headers=csrf_headers(token),
        )

        logged = rendered(logs)
        assert SECRET not in logged
        assert ADMIN_PASSWORD not in logged

    async def test_no_request_body_is_logged_at_all(
        self, db_client: AsyncClient, db_session: AsyncSession, logs: LogReader
    ) -> None:
        """The safest rule for a credential-bearing endpoint is to log no body."""
        await create_admin(db_session, email="admin@example.com")
        token = await log_in(db_client, email="admin@example.com", password=ADMIN_PASSWORD)

        await db_client.post(
            "/api/v1/auth/password",
            json={"current_password": ADMIN_PASSWORD, "new_password": SECRET},
            headers=csrf_headers(token),
        )

        logged = rendered(logs)
        assert "current_password" not in logged
        assert "new_password" not in logged

    async def test_provisioning_does_not_log_the_temporary_password(
        self, db_client: AsyncClient, db_session: AsyncSession, logs: LogReader
    ) -> None:
        await create_admin(db_session, email="admin@example.com")
        token = await log_in(db_client, email="admin@example.com", password=ADMIN_PASSWORD)

        created = await db_client.post(
            "/api/v1/users",
            json={"email": "hire@example.com", "full_name": "New Hire", "role": "EMPLOYEE"},
            headers=csrf_headers(token),
        )

        assert created.json()["temporary_password"] not in rendered(logs)


class TestTheDatabaseHoldsNoPlaintextColumns:
    async def test_no_column_is_named_as_if_it_held_a_password(
        self, db_session: AsyncSession
    ) -> None:
        """A `password` column would be a design error visible from the schema alone."""
        columns = {
            f"{table.name}.{column.name}"
            for table in Base.metadata.sorted_tables
            for column in table.columns
        }

        assert not {name for name in columns if name.endswith(".password")}
        assert "user_identities.secret_hash" in columns
