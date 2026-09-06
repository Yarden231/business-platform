"""Cookie attributes (docs/security.md §3, ADR-0005).

These tests read the real `Set-Cookie` headers rather than asserting that some
header exists, because every attribute here is the control: `HttpOnly` is what
keeps the session token away from injected script, `SameSite` is what withholds
it from cross-site form posts, and a stray `Domain` would hand the cookie to
every subdomain.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cookies import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
from app.core.settings import get_settings
from app.db.session import get_db_session
from tests.conftest import build_client
from tests.support.accounts import EMPLOYEE_PASSWORD, create_employee, csrf_headers, log_in


def cookie_header(response: Response, name: str) -> str:
    """The raw `Set-Cookie` line for `name`."""
    headers = [
        value for value in response.headers.get_list("set-cookie") if value.startswith(f"{name}=")
    ]
    assert len(headers) == 1, f"expected exactly one {name} cookie, got {headers}"
    return str(headers[0])


def attributes(header: str) -> dict[str, str]:
    """The attributes of a `Set-Cookie` line, lower-cased, value-less ones as `""`."""
    parsed: dict[str, str] = {}
    for part in header.split(";")[1:]:
        key, _, value = part.strip().partition("=")
        parsed[key.lower()] = value
    return parsed


class TestSessionCookie:
    @pytest.fixture
    async def login_response(self, db_client: AsyncClient, db_session: AsyncSession) -> object:
        await create_employee(db_session)
        return await db_client.post(
            "/api/v1/auth/login",
            json={"email": "employee@example.com", "password": EMPLOYEE_PASSWORD},
        )

    def test_it_is_not_readable_from_javascript(self, login_response: Response) -> None:
        """The whole point: an XSS cannot exfiltrate a token it cannot read."""
        assert "httponly" in attributes(cookie_header(login_response, SESSION_COOKIE_NAME))

    def test_it_is_withheld_from_cross_site_form_posts(self, login_response: Response) -> None:
        """`Lax`, not `Strict` — following a link from an email must not log you out."""
        assert attributes(cookie_header(login_response, SESSION_COOKIE_NAME))["samesite"] == "lax"

    def test_it_covers_the_whole_application(self, login_response: Response) -> None:
        assert attributes(cookie_header(login_response, SESSION_COOKIE_NAME))["path"] == "/"

    def test_it_is_host_only(self, login_response: Response) -> None:
        """No `Domain`, so the cookie is never shared with a sibling subdomain."""
        assert "domain" not in attributes(cookie_header(login_response, SESSION_COOKIE_NAME))

    def test_it_expires_with_the_browser_session(self, login_response: Response) -> None:
        """No `Max-Age` or `Expires`: the server-side row is the only authority on lifetime."""
        parsed = attributes(cookie_header(login_response, SESSION_COOKIE_NAME))

        assert "max-age" not in parsed
        assert "expires" not in parsed

    def test_it_is_not_secure_in_local_development(self, login_response: Response) -> None:
        """Local development is plain HTTP; a `Secure` cookie would never be sent."""
        assert "secure" not in attributes(cookie_header(login_response, SESSION_COOKIE_NAME))

    def test_the_cookie_value_is_the_opaque_token(self, login_response: Response) -> None:
        """Not a signed payload, not a JWT: it means nothing without the session row."""
        header = cookie_header(login_response, SESSION_COOKIE_NAME)
        value = header.split(";")[0].removeprefix(f"{SESSION_COOKIE_NAME}=")

        assert len(value) >= 43
        assert "." not in value  # not a JWT
        assert "@" not in value  # no identifier smuggled in


class TestCsrfCookie:
    @pytest.fixture
    async def login_response(self, db_client: AsyncClient, db_session: AsyncSession) -> object:
        await create_employee(db_session)
        return await db_client.post(
            "/api/v1/auth/login",
            json={"email": "employee@example.com", "password": EMPLOYEE_PASSWORD},
        )

    def test_it_is_readable_from_javascript_on_purpose(self, login_response: Response) -> None:
        """The client's job is to read it and echo it back as a header."""
        assert "httponly" not in attributes(cookie_header(login_response, CSRF_COOKIE_NAME))

    def test_it_carries_the_same_same_site_and_path_policy(self, login_response: Response) -> None:
        parsed = attributes(cookie_header(login_response, CSRF_COOKIE_NAME))

        assert parsed["samesite"] == "lax"
        assert parsed["path"] == "/"
        assert "domain" not in parsed


class TestProductionCookies:
    """The `Secure` flag, proved against a production-configured application."""

    @pytest.fixture
    def production_settings(self, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
        monkeypatch.setenv("SESSION_COOKIE_SECURE", "true")
        get_settings.cache_clear()
        yield
        get_settings.cache_clear()

    @pytest.fixture
    async def secure_client(
        self, production_settings: None, db_session: AsyncSession
    ) -> AsyncIterator[AsyncClient]:
        from app.main import create_app

        app: FastAPI = create_app()

        async def _override() -> AsyncIterator[AsyncSession]:
            yield db_session

        app.dependency_overrides[get_db_session] = _override
        # Over `https`, because a client only keeps a `Secure` cookie that
        # arrived over TLS — which is the behaviour being relied on.
        async with build_client(app, tls=True) as client:
            yield client

    async def test_both_cookies_are_secure(
        self, secure_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await create_employee(db_session)

        response = await secure_client.post(
            "/api/v1/auth/login",
            json={"email": "employee@example.com", "password": EMPLOYEE_PASSWORD},
        )

        assert "secure" in attributes(cookie_header(response, SESSION_COOKIE_NAME))
        assert "secure" in attributes(cookie_header(response, CSRF_COOKIE_NAME))

    async def test_logout_clears_them_with_the_same_attributes(
        self, secure_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A deletion is matched by name, path and domain, so they have to agree."""
        await create_employee(db_session)
        token = await log_in(
            secure_client, email="employee@example.com", password=EMPLOYEE_PASSWORD
        )

        response = await secure_client.post("/api/v1/auth/logout", headers=csrf_headers(token))

        for name in (SESSION_COOKIE_NAME, CSRF_COOKIE_NAME):
            parsed = attributes(cookie_header(response, name))
            assert parsed["path"] == "/"
            assert "secure" in parsed
            assert "domain" not in parsed


class TestLogoutClearsCookies:
    async def test_both_cookies_are_expired(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await create_employee(db_session)
        token = await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        response = await db_client.post("/api/v1/auth/logout", headers=csrf_headers(token))

        for name in (SESSION_COOKIE_NAME, CSRF_COOKIE_NAME):
            parsed = attributes(cookie_header(response, name))
            assert parsed.get("max-age") == "0" or parsed.get("expires")

    async def test_the_client_jar_ends_up_empty(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """What a real browser would do with those headers."""
        await create_employee(db_session)
        token = await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        await db_client.post("/api/v1/auth/logout", headers=csrf_headers(token))

        assert SESSION_COOKIE_NAME not in db_client.cookies
        assert CSRF_COOKIE_NAME not in db_client.cookies

    async def test_the_session_cookie_deletion_keeps_httponly(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await create_employee(db_session)
        token = await log_in(db_client, email="employee@example.com", password=EMPLOYEE_PASSWORD)

        response = await db_client.post("/api/v1/auth/logout", headers=csrf_headers(token))

        assert "httponly" in attributes(cookie_header(response, SESSION_COOKIE_NAME))
