"""The liveness endpoint, and what the API contract publishes."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.core.errors import ErrorCode


@pytest.mark.parametrize("path", ["/healthz", "/api/v1/healthz"])
async def test_healthz_reports_ok(client: AsyncClient, path: str) -> None:
    response = await client.get(path)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_healthz_response_carries_nothing_beyond_status(client: AsyncClient) -> None:
    response = await client.get("/healthz")

    assert list(response.json()) == ["status"]


def test_openapi_publishes_the_versioned_probes_only(app: FastAPI) -> None:
    """The unversioned paths are infrastructure probes, so they stay out of the contract.

    `/api/v1/*` is what the web application calls, so it is published and will
    appear in the generated TypeScript types.
    """
    paths = app.openapi()["paths"]

    assert "/api/v1/healthz" in paths
    assert "/api/v1/readyz" in paths
    assert "/healthz" not in paths
    assert "/readyz" not in paths


def test_openapi_publishes_the_error_code_enum(app: FastAPI) -> None:
    """ADR-0039: the envelope's `code` is the ErrorCode enum, so the generated
    client types stay exhaustive as new codes are added.
    """
    schema = app.openapi()["components"]["schemas"]["ErrorCode"]
    assert set(schema["enum"]) == {member.value for member in ErrorCode}
