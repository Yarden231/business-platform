"""Security headers, CORS and the API documentation policy (docs/security.md §8)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core.settings import get_settings
from app.main import create_app
from tests.conftest import build_client

PRODUCTION_ENV = {
    "APP_ENV": "production",
    "DATABASE_URL": "postgresql+asyncpg://api:s3cret@db.example.net:5432/cohen?ssl=require",
    "SESSION_SECRET": "x" * 64,
    "CORS_ALLOWED_ORIGINS": "",
}


@pytest.fixture
def production_client(monkeypatch: pytest.MonkeyPatch) -> AsyncClient:
    for name, value in PRODUCTION_ENV.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    return build_client(create_app())


class TestSecurityHeaders:
    @pytest.mark.parametrize(
        ("header", "value"),
        [
            ("x-content-type-options", "nosniff"),
            ("referrer-policy", "strict-origin-when-cross-origin"),
            ("x-frame-options", "DENY"),
        ],
    )
    async def test_every_response_carries_it(
        self, client: AsyncClient, header: str, value: str
    ) -> None:
        response = await client.get("/healthz")

        assert response.headers[header] == value

    async def test_error_responses_carry_them_too(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/nothing-here")

        assert response.status_code == 404
        assert response.headers["x-content-type-options"] == "nosniff"

    async def test_no_content_security_policy_is_set_here(self, client: AsyncClient) -> None:
        """CSP governs what a browser renders, which is the Next.js origin, not this API."""
        response = await client.get("/healthz")

        assert "content-security-policy" not in response.headers


class TestCors:
    async def test_the_development_origin_is_allowed(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/healthz", headers={"Origin": "http://localhost:3000"})

        assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
        assert response.headers["access-control-allow-credentials"] == "true"

    async def test_an_unlisted_origin_gets_no_allowance(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/healthz", headers={"Origin": "https://evil.example"})

        assert "access-control-allow-origin" not in response.headers

    async def test_production_allows_no_cross_origin_access_at_all(
        self, production_client: AsyncClient
    ) -> None:
        async with production_client as client:
            response = await client.get(
                "/api/v1/healthz", headers={"Origin": "http://localhost:3000"}
            )

        assert "access-control-allow-origin" not in response.headers


class TestApiDocumentation:
    @pytest.mark.parametrize("path", ["/docs", "/openapi.json"])
    async def test_available_outside_production(self, client: AsyncClient, path: str) -> None:
        response = await client.get(path)

        assert response.status_code == 200

    @pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
    async def test_disabled_in_production(self, production_client: AsyncClient, path: str) -> None:
        async with production_client as client:
            response = await client.get(path)

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"
