"""The error envelope: one shape, no leaks.

Everything here is asserted through the HTTP boundary rather than against the
handler functions, because the contract is what a caller receives.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.core.errors import ConflictError, ErrorDetail, NotFoundError
from tests.conftest import build_client

SECRET_IN_THE_EXCEPTION = "postgresql://cohen:local_dev_password@db:5432/cohen_balancing"


@pytest.fixture
def app_with_failing_routes(app: FastAPI) -> FastAPI:
    """Routes that fail in the three ways the platform has to handle."""

    @app.get("/test/boom")
    async def boom() -> None:
        raise RuntimeError(f"connection to {SECRET_IN_THE_EXCEPTION} failed")

    @app.get("/test/known-error")
    async def known_error() -> None:
        raise ConflictError(
            "That internal case number already exists.",
            details=[ErrorDetail(field="internal_case_number", issue="already_taken")],
        )

    @app.get("/test/not-found")
    async def not_found() -> None:
        raise NotFoundError

    @app.get("/test/validated")
    async def validated(count: int) -> dict[str, int]:
        return {"count": count}

    return app


@pytest.fixture
async def failing_client(app_with_failing_routes: FastAPI) -> AsyncIterator[AsyncClient]:
    async with build_client(app_with_failing_routes) as async_client:
        yield async_client


def assert_is_envelope(payload: dict[str, Any], *, code: str) -> dict[str, Any]:
    assert list(payload) == ["error"]
    error: dict[str, Any] = payload["error"]
    assert sorted(error) == ["code", "details", "message", "request_id"]
    assert error["code"] == code
    assert isinstance(error["message"], str)
    assert isinstance(error["details"], list)
    UUID(error["request_id"])  # server-generated, and a real one
    return error


async def test_an_application_error_becomes_its_documented_envelope(
    failing_client: AsyncClient,
) -> None:
    response = await failing_client.get("/test/known-error")

    assert response.status_code == 409
    error = assert_is_envelope(response.json(), code="CONFLICT")
    assert error["message"] == "That internal case number already exists."
    assert error["details"] == [{"field": "internal_case_number", "issue": "already_taken"}]


async def test_an_error_class_default_message_is_used_when_none_is_given(
    failing_client: AsyncClient,
) -> None:
    response = await failing_client.get("/test/not-found")

    assert response.status_code == 404
    assert_is_envelope(response.json(), code="NOT_FOUND")


async def test_an_unknown_route_uses_the_same_envelope(client: AsyncClient) -> None:
    response = await client.get("/api/v1/nothing-here")

    assert response.status_code == 404
    assert_is_envelope(response.json(), code="NOT_FOUND")


async def test_a_wrong_method_uses_the_same_envelope(client: AsyncClient) -> None:
    response = await client.post("/api/v1/healthz")

    assert response.status_code == 405
    assert_is_envelope(response.json(), code="METHOD_NOT_ALLOWED")


async def test_validation_failures_report_the_field_but_never_the_value(
    failing_client: AsyncClient,
) -> None:
    response = await failing_client.get("/test/validated", params={"count": "not-a-number"})

    assert response.status_code == 422
    error = assert_is_envelope(response.json(), code="VALIDATION_ERROR")
    assert error["details"] == [{"field": "count", "issue": "int_parsing"}]
    # Pydantic's `input` and `msg` are omitted on purpose: echoing the rejected
    # value would put a password or an ID number in the response body.
    assert "not-a-number" not in response.text


class TestUnexpectedFailures:
    async def test_the_caller_gets_a_generic_five_hundred(
        self, failing_client: AsyncClient
    ) -> None:
        response = await failing_client.get("/test/boom")

        assert response.status_code == 500
        error = assert_is_envelope(response.json(), code="INTERNAL_ERROR")
        assert error["message"] == "An unexpected error occurred."
        assert error["details"] == []

    async def test_nothing_internal_is_disclosed(self, failing_client: AsyncClient) -> None:
        response = await failing_client.get("/test/boom")
        body = response.text

        assert SECRET_IN_THE_EXCEPTION not in body
        assert "local_dev_password" not in body
        assert "RuntimeError" not in body
        assert "Traceback" not in body
        assert "app/api" not in body
        assert "site-packages" not in body

    async def test_the_response_still_carries_the_request_id_and_security_headers(
        self, failing_client: AsyncClient
    ) -> None:
        """A 500 is rendered outside the middleware stack, so this is easy to lose."""
        response = await failing_client.get("/test/boom")

        assert response.headers["x-request-id"] == response.json()["error"]["request_id"]
        assert response.headers["x-content-type-options"] == "nosniff"
